"""Sales orders, order lines, reservations (read), payments (PRD §3.5, §3.6)."""
from collections import defaultdict

from flask import Blueprint, request

import db
from errors import ApiError
from middleware import authenticate, require_roles
from response import ok, created, list_ok
import helpers as h
import services as svc

bp = Blueprint("sales", __name__)


# ---------------- SalesOrder ----------------
@bp.route("/shop/sales-orders", methods=["POST"])
def create_sales_order():
    _, role = authenticate()
    require_roles(role, ["SalesAssociate", "ShopManager"])
    body = h.get_body()
    with db.LOCK:
        customer_id = h.require_str(body, "customer_id")
        h.must_exist(db.customers, customer_id)
        rec = {
            "customer_id": customer_id,
            "payment_status": "UNPAID",
            "fulfillment_status": "PENDING",
            "subtotal_cents": 0,
            "store_credit_applied_cents": 0,
            "total_due_cents": 0,
            "amount_paid_cents": 0,
        }
        h.stamp_create(rec)
        db.sales_orders[rec["id"]] = rec
        return created(h.public(rec))


@bp.route("/shop/sales-orders/<oid>", methods=["GET"])
def read_sales_order(oid):
    _, role = authenticate()
    require_roles(role, ["SalesAssociate", "ServiceAdvisor", "ShopManager", "Customer"])
    with db.LOCK:
        rec = h.must_exist(db.sales_orders, oid)
        # refresh totals for the response (calc order_total), preserving any
        # applied store credit / refunded status already settled.
        if rec["payment_status"] != "REFUNDED" and rec["fulfillment_status"] != "DELIVERED":
            svc.recompute_order_total(rec)
        return ok(h.public(rec))


@bp.route("/shop/sales-orders", methods=["GET"])
def list_sales_orders():
    _, role = authenticate()
    require_roles(role, ["SalesAssociate", "ServiceAdvisor", "ShopManager"])
    with db.LOCK:
        recs = list(db.sales_orders.values())
        v = request.args.get("customer_id")
        if v is not None:
            recs = [r for r in recs if r["customer_id"] == v]
        items, limit, offset, total = h.paginate(recs)
        return list_ok(items, limit, offset, total)


@bp.route("/shop/sales-orders/<oid>/reserve", methods=["POST"])
def reserve_sales_order(oid):
    _, role = authenticate()
    require_roles(role, ["SalesAssociate", "ShopManager"])
    body = h.get_body()
    with db.LOCK:
        rec = h.must_exist(db.sales_orders, oid)
        expected_version = h.require_int(body, "expected_sku_version")
        # priority 5: state
        if rec["fulfillment_status"] != "PENDING":
            raise ApiError("ERR_INVALID_STATE", "Reserve requires PENDING fulfillment.")
        lines = [l for l in db.order_lines.values() if l["order_id"] == oid]
        if len(lines) < 1:
            raise ApiError("ERR_INVALID_STATE", "Order has no lines.")
        # primary Sku = the Sku of the order's first-created line (OCC anchor)
        lines_sorted = sorted(lines, key=lambda l: l["_seq"])
        primary_sku = db.skus[lines_sorted[0]["sku_id"]]

        # aggregate requested qty per sku (over the SUM of all lines)
        per_sku = defaultdict(int)
        for l in lines:
            per_sku[l["sku_id"]] += l["qty"]

        # priority 12: MANDATORY recall block (before availability)
        for sku_id in per_sku:
            if svc.has_mandatory_recall(sku_id):
                raise ApiError("ERR_RECALL_BLOCK", "Sku is under a MANDATORY recall.")
        # priority 13: availability over the summed qty
        for sku_id, qty in per_sku.items():
            if svc.available_units(db.skus[sku_id]) < qty:
                raise ApiError("ERR_INSUFFICIENT_STOCK", "Insufficient available units.")
        # priority 17: OCC on the primary Sku
        if expected_version != primary_sku["version"]:
            raise ApiError("ERR_STALE_VERSION", "Sku version is stale.")

        # commit: create one ACTIVE reservation per OrderLine
        for l in lines:
            svc.create_reservation(l["sku_id"], "SALES_ORDER", oid, l["qty"])
        # bump primary Sku version, refresh availability for all touched skus
        h.touch(primary_sku)
        svc.reconcile_sku(primary_sku)
        rec["fulfillment_status"] = "RESERVED"
        h.touch(rec)
        svc.recompute_order_total(rec)
        return ok(h.public(rec))


@bp.route("/shop/sales-orders/<oid>/deliver", methods=["POST"])
def deliver_sales_order(oid):
    _, role = authenticate()
    require_roles(role, ["SalesAssociate", "ShopManager"])
    with db.LOCK:
        rec = h.must_exist(db.sales_orders, oid)
        if rec["fulfillment_status"] != "RESERVED":
            raise ApiError("ERR_INVALID_STATE", "Deliver requires RESERVED fulfillment.")
        # store-credit waterfall runs first (PRD §3.5/§3.6), before PAID re-eval
        svc.recompute_order_total(rec)  # refresh subtotal/paid before credit
        svc.apply_store_credit(rec)
        svc.recompute_order_total_zero_safe(rec)
        # priority 14: must be PAID after applying store credit
        if rec["payment_status"] != "PAID":
            raise ApiError("ERR_NOT_FULLY_PAID", "Order is not fully paid.")
        for res in svc.active_reservations_for("SALES_ORDER", oid):
            svc.commit_reservation(res)
        rec["fulfillment_status"] = "DELIVERED"
        h.touch(rec)
        svc.recompute_order_total_zero_safe(rec)
        return ok(h.public(rec))


@bp.route("/shop/sales-orders/<oid>/cancel", methods=["POST"])
def cancel_sales_order(oid):
    _, role = authenticate()
    require_roles(role, ["SalesAssociate", "ShopManager"])
    with db.LOCK:
        rec = h.must_exist(db.sales_orders, oid)
        if rec["fulfillment_status"] not in ("PENDING", "RESERVED"):
            raise ApiError("ERR_INVALID_STATE", "Cancel requires PENDING or RESERVED.")
        for res in svc.active_reservations_for("SALES_ORDER", oid):
            svc.release_reservation(res)
        if rec["payment_status"] in ("PARTIALLY_PAID", "PAID"):
            rec["payment_status"] = "REFUNDED"
            for p in db.payments.values():
                if (p["target_type"] == "SALES_ORDER" and p["target_id"] == oid
                        and p["status"] == "CAPTURED"):
                    p["status"] = "VOIDED"
            # restore consumed store credit (compensation)
            consumed = rec.get("store_credit_applied_cents", 0)
            if consumed > 0:
                customer = db.customers[rec["customer_id"]]
                customer["store_credit_cents"] += consumed
                h.touch(customer)
        rec["fulfillment_status"] = "CANCELLED"
        h.touch(rec)
        return ok(h.public(rec))


# ---------------- OrderLine ----------------
@bp.route("/shop/order-lines", methods=["POST"])
def create_order_line():
    _, role = authenticate()
    require_roles(role, ["SalesAssociate", "ShopManager"])
    body = h.get_body()
    with db.LOCK:
        order_id = h.require_str(body, "order_id")
        sku_id = h.require_str(body, "sku_id")
        qty = h.require_int(body, "qty", minimum=1)
        order = h.must_exist(db.sales_orders, order_id)
        sku = h.must_exist(db.skus, sku_id)
        # lines are added to a PENDING order (PRD §3.5)
        if order["fulfillment_status"] != "PENDING":
            raise ApiError("ERR_INVALID_STATE", "Lines may only be added to a PENDING order.")
        rec = {
            "order_id": order_id,
            "sku_id": sku_id,
            "qty": qty,
            "unit_price_cents": sku["list_price_cents"],
        }
        h.stamp_create(rec)
        db.order_lines[rec["id"]] = rec
        svc.recompute_order_total(order)
        return created(h.public(rec))


@bp.route("/shop/order-lines/<lid>", methods=["GET"])
def read_order_line(lid):
    _, role = authenticate()
    require_roles(role, ["SalesAssociate", "ServiceAdvisor", "ShopManager", "Customer"])
    with db.LOCK:
        rec = h.must_exist(db.order_lines, lid)
        return ok(h.public(rec))


@bp.route("/shop/order-lines", methods=["GET"])
def list_order_lines():
    _, role = authenticate()
    require_roles(role, ["SalesAssociate", "ServiceAdvisor", "ShopManager"])
    with db.LOCK:
        recs = list(db.order_lines.values())
        for f in ("order_id", "sku_id"):
            v = request.args.get(f)
            if v is not None:
                recs = [r for r in recs if r[f] == v]
        items, limit, offset, total = h.paginate(recs)
        return list_ok(items, limit, offset, total)


# ---------------- Reservation (read-only) ----------------
@bp.route("/shop/reservations/<rid>", methods=["GET"])
def read_reservation(rid):
    _, role = authenticate()
    require_roles(role, ["SalesAssociate", "ServiceAdvisor", "ShopManager"])
    with db.LOCK:
        rec = h.must_exist(db.reservations, rid)
        return ok(h.public(rec))


@bp.route("/shop/reservations", methods=["GET"])
def list_reservations():
    _, role = authenticate()
    require_roles(role, ["SalesAssociate", "ServiceAdvisor", "ShopManager"])
    with db.LOCK:
        recs = list(db.reservations.values())
        for f in ("sku_id", "holder_type", "holder_id", "status"):
            v = request.args.get(f)
            if v is not None:
                recs = [r for r in recs if r[f] == v]
        items, limit, offset, total = h.paginate(recs)
        return list_ok(items, limit, offset, total)


# ---------------- Payment ----------------
PAYMENT_TARGETS = {"SALES_ORDER", "LAYAWAY_PLAN", "SPECIAL_ORDER"}


@bp.route("/shop/payments", methods=["POST"])
def create_payment():
    _, role = authenticate()
    require_roles(role, ["SalesAssociate", "ShopManager"])
    body = h.get_body()
    with db.LOCK:
        target_type = h.require_enum(body, "target_type", PAYMENT_TARGETS)
        target_id = h.require_str(body, "target_id")
        amount = h.require_int(body, "amount_cents", minimum=1)
        # existence + payability per target type (priority 18)
        if target_type == "SALES_ORDER":
            target = h.must_exist(db.sales_orders, target_id)
            if target["fulfillment_status"] in ("CANCELLED", "DELIVERED"):
                raise ApiError("ERR_TARGET_NOT_PAYABLE", "Order no longer accepts payments.")
            if target["payment_status"] not in ("UNPAID", "PARTIALLY_PAID"):
                raise ApiError("ERR_TARGET_NOT_PAYABLE", "Order no longer accepts payments.")
        elif target_type == "LAYAWAY_PLAN":
            target = h.must_exist(db.layaway_plans, target_id)
            if target["status"] != "ACTIVE":
                raise ApiError("ERR_TARGET_NOT_PAYABLE", "Plan no longer accepts payments.")
        else:  # SPECIAL_ORDER
            target = h.must_exist(db.special_orders, target_id)
            if target["status"] in ("FULFILLED", "CANCELLED"):
                raise ApiError("ERR_TARGET_NOT_PAYABLE", "Special order no longer accepts payments.")

        rec = {
            "target_type": target_type,
            "target_id": target_id,
            "amount_cents": amount,
            "status": "CAPTURED",
        }
        h.stamp_create(rec, ledger=True)
        db.payments[rec["id"]] = rec

        # recompute target & bump its version
        if target_type == "SALES_ORDER":
            svc.recompute_order_total(target)
            h.touch(target)
        elif target_type == "LAYAWAY_PLAN":
            target["deposit_cents"] = svc.deposit_sum("LAYAWAY_PLAN", target_id)
            h.touch(target)
        else:
            target["deposit_paid_cents"] = svc.deposit_sum("SPECIAL_ORDER", target_id)
            h.touch(target)
        return created(h.public(rec))


@bp.route("/shop/payments", methods=["GET"])
def list_payments():
    _, role = authenticate()
    require_roles(role, ["SalesAssociate", "ServiceAdvisor", "ShopManager"])
    with db.LOCK:
        recs = list(db.payments.values())
        for f in ("target_type", "target_id"):
            v = request.args.get(f)
            if v is not None:
                recs = [r for r in recs if r[f] == v]
        items, limit, offset, total = h.paginate(recs)
        return list_ok(items, limit, offset, total)
