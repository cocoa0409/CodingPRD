"""Layaway plans and special orders (PRD §3.7, §3.8)."""
from flask import Blueprint, request

import db
from errors import ApiError
from middleware import authenticate, require_roles
from response import ok, created, list_ok
import helpers as h
import services as svc

bp = Blueprint("holders", __name__)


# ---------------- LayawayPlan ----------------
@bp.route("/shop/layaway-plans", methods=["POST"])
def open_layaway():
    _, role = authenticate()
    require_roles(role, ["SalesAssociate", "ShopManager"])
    body = h.get_body()
    with db.LOCK:
        customer_id = h.require_str(body, "customer_id")
        sku_id = h.require_str(body, "sku_id")
        qty = h.optional_int(body, "qty", default=1, minimum=1)
        expected_version = h.require_int(body, "expected_sku_version")
        h.must_exist(db.customers, customer_id)
        sku = h.must_exist(db.skus, sku_id)
        # priority 12: MANDATORY recall block (before availability)
        if svc.has_mandatory_recall(sku_id):
            raise ApiError("ERR_RECALL_BLOCK", "Sku is under a MANDATORY recall.")
        # priority 13: availability
        if svc.available_units(sku) < qty:
            raise ApiError("ERR_INSUFFICIENT_STOCK", "Insufficient available units.")
        # priority 17: OCC
        if expected_version != sku["version"]:
            raise ApiError("ERR_STALE_VERSION", "Sku version is stale.")
        rec = {
            "customer_id": customer_id,
            "sku_id": sku_id,
            "qty": qty,
            "price_cents": sku["list_price_cents"] * qty,
            "deposit_cents": 0,
            "status": "ACTIVE",
            "forfeit_fee_cents": 0,
            "refund_cents": 0,
        }
        h.stamp_create(rec)
        db.layaway_plans[rec["id"]] = rec
        svc.create_reservation(sku_id, "LAYAWAY_PLAN", rec["id"], qty)
        h.touch(sku)
        svc.reconcile_sku(sku)
        return created(h.public(rec))


@bp.route("/shop/layaway-plans/<pid>", methods=["GET"])
def read_layaway(pid):
    _, role = authenticate()
    require_roles(role, ["SalesAssociate", "ServiceAdvisor", "ShopManager", "Customer"])
    with db.LOCK:
        rec = h.must_exist(db.layaway_plans, pid)
        return ok(h.public(rec))


@bp.route("/shop/layaway-plans", methods=["GET"])
def list_layaway():
    _, role = authenticate()
    require_roles(role, ["SalesAssociate", "ServiceAdvisor", "ShopManager"])
    with db.LOCK:
        recs = list(db.layaway_plans.values())
        for f in ("customer_id", "sku_id"):
            v = request.args.get(f)
            if v is not None:
                recs = [r for r in recs if r[f] == v]
        items, limit, offset, total = h.paginate(recs)
        return list_ok(items, limit, offset, total)


@bp.route("/shop/layaway-plans/<pid>/fulfill", methods=["POST"])
def fulfill_layaway(pid):
    _, role = authenticate()
    require_roles(role, ["SalesAssociate", "ShopManager"])
    with db.LOCK:
        rec = h.must_exist(db.layaway_plans, pid)
        if rec["status"] != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE", "Fulfill requires ACTIVE.")
        # priority 16
        if rec["deposit_cents"] < rec["price_cents"]:
            raise ApiError("ERR_LAYAWAY_NOT_PAID_OFF", "Plan is not paid off.")
        for res in svc.active_reservations_for("LAYAWAY_PLAN", pid):
            svc.commit_reservation(res)
        rec["status"] = "FULFILLED"
        h.touch(rec)
        return ok(h.public(rec))


@bp.route("/shop/layaway-plans/<pid>/forfeit", methods=["POST"])
def forfeit_layaway(pid):
    _, role = authenticate()
    require_roles(role, ["ShopManager"])
    with db.LOCK:
        rec = h.must_exist(db.layaway_plans, pid)
        if rec["status"] != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE", "Forfeit requires ACTIVE.")
        for res in svc.active_reservations_for("LAYAWAY_PLAN", pid):
            svc.release_reservation(res)
        svc.layaway_settle_forfeit(rec)
        if rec["refund_cents"] > 0:
            customer = db.customers[rec["customer_id"]]
            customer["store_credit_cents"] += rec["refund_cents"]
            h.touch(customer)
        rec["status"] = "FORFEITED"
        h.touch(rec)
        return ok(h.public(rec))


@bp.route("/shop/layaway-plans/<pid>/cancel", methods=["POST"])
def cancel_layaway(pid):
    _, role = authenticate()
    require_roles(role, ["SalesAssociate", "ShopManager"])
    with db.LOCK:
        rec = h.must_exist(db.layaway_plans, pid)
        if rec["status"] != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE", "Cancel requires ACTIVE.")
        for res in svc.active_reservations_for("LAYAWAY_PLAN", pid):
            svc.release_reservation(res)
        svc.layaway_settle_cancel(rec)
        if rec["refund_cents"] > 0:
            customer = db.customers[rec["customer_id"]]
            customer["store_credit_cents"] += rec["refund_cents"]
            h.touch(customer)
        rec["status"] = "CANCELLED"
        h.touch(rec)
        return ok(h.public(rec))


# ---------------- SpecialOrder ----------------
@bp.route("/shop/special-orders", methods=["POST"])
def create_special_order():
    _, role = authenticate()
    require_roles(role, ["SalesAssociate", "ShopManager"])
    body = h.get_body()
    with db.LOCK:
        customer_id = h.require_str(body, "customer_id")
        sku_id = h.require_str(body, "sku_id")
        qty = h.require_int(body, "qty", minimum=1)
        h.must_exist(db.customers, customer_id)
        sku = h.must_exist(db.skus, sku_id)
        line_value = sku["list_price_cents"] * qty
        rec = {
            "customer_id": customer_id,
            "sku_id": sku_id,
            "qty": qty,
            "deposit_required_cents": svc.special_order_deposit(line_value),
            "deposit_paid_cents": 0,
            "status": "QUOTED",
        }
        h.stamp_create(rec)
        db.special_orders[rec["id"]] = rec
        return created(h.public(rec))


@bp.route("/shop/special-orders/<sid>", methods=["GET"])
def read_special_order(sid):
    _, role = authenticate()
    require_roles(role, ["SalesAssociate", "ServiceAdvisor", "ShopManager", "Customer"])
    with db.LOCK:
        rec = h.must_exist(db.special_orders, sid)
        return ok(h.public(rec))


@bp.route("/shop/special-orders", methods=["GET"])
def list_special_orders():
    _, role = authenticate()
    require_roles(role, ["SalesAssociate", "ServiceAdvisor", "ShopManager"])
    with db.LOCK:
        recs = list(db.special_orders.values())
        for f in ("customer_id", "sku_id"):
            v = request.args.get(f)
            if v is not None:
                recs = [r for r in recs if r[f] == v]
        items, limit, offset, total = h.paginate(recs)
        return list_ok(items, limit, offset, total)


@bp.route("/shop/special-orders/<sid>/confirm", methods=["POST"])
def confirm_special_order(sid):
    _, role = authenticate()
    require_roles(role, ["SalesAssociate", "ShopManager"])
    with db.LOCK:
        rec = h.must_exist(db.special_orders, sid)
        if rec["status"] != "QUOTED":
            raise ApiError("ERR_INVALID_STATE", "Confirm requires QUOTED.")
        # priority 15
        if rec["deposit_paid_cents"] < rec["deposit_required_cents"]:
            raise ApiError("ERR_DEPOSIT_SHORT", "Deposit is short.")
        rec["status"] = "CONFIRMED"
        h.touch(rec)
        return ok(h.public(rec))


@bp.route("/shop/special-orders/<sid>/receive", methods=["POST"])
def receive_special_order(sid):
    _, role = authenticate()
    require_roles(role, ["SalesAssociate", "ShopManager"])
    with db.LOCK:
        rec = h.must_exist(db.special_orders, sid)
        if rec["status"] != "CONFIRMED":
            raise ApiError("ERR_INVALID_STATE", "Receive requires CONFIRMED.")
        sku = db.skus[rec["sku_id"]]
        # priority 12: MANDATORY recall block
        if svc.has_mandatory_recall(rec["sku_id"]):
            raise ApiError("ERR_RECALL_BLOCK", "Sku is under a MANDATORY recall.")
        sku["on_hand"] += rec["qty"]
        h.touch(sku)
        svc.create_reservation(rec["sku_id"], "SPECIAL_ORDER", sid, rec["qty"])
        svc.reconcile_sku(sku)
        rec["status"] = "ARRIVED"
        h.touch(rec)
        return ok(h.public(rec))


@bp.route("/shop/special-orders/<sid>/fulfill", methods=["POST"])
def fulfill_special_order(sid):
    _, role = authenticate()
    require_roles(role, ["SalesAssociate", "ShopManager"])
    with db.LOCK:
        rec = h.must_exist(db.special_orders, sid)
        if rec["status"] != "ARRIVED":
            raise ApiError("ERR_INVALID_STATE", "Fulfill requires ARRIVED.")
        for res in svc.active_reservations_for("SPECIAL_ORDER", sid):
            svc.commit_reservation(res)
        rec["status"] = "FULFILLED"
        h.touch(rec)
        return ok(h.public(rec))


@bp.route("/shop/special-orders/<sid>/cancel", methods=["POST"])
def cancel_special_order(sid):
    _, role = authenticate()
    require_roles(role, ["SalesAssociate", "ShopManager"])
    with db.LOCK:
        rec = h.must_exist(db.special_orders, sid)
        if rec["status"] not in ("QUOTED", "CONFIRMED"):
            raise ApiError("ERR_INVALID_STATE", "Cancel requires QUOTED or CONFIRMED.")
        was_quoted = rec["status"] == "QUOTED"
        # release any reservation (only exists once received, but cancel is only
        # from QUOTED/CONFIRMED so normally none — defensive per scaffold note)
        for res in svc.active_reservations_for("SPECIAL_ORDER", sid):
            svc.release_reservation(res)
        # deposit handling: QUOTED -> refund by voiding payments; CONFIRMED -> non-refundable
        if was_quoted:
            for p in db.payments.values():
                if (p["target_type"] == "SPECIAL_ORDER" and p["target_id"] == sid
                        and p["status"] == "CAPTURED"):
                    p["status"] = "VOIDED"
            rec["deposit_paid_cents"] = svc.deposit_sum("SPECIAL_ORDER", sid)
        rec["status"] = "CANCELLED"
        h.touch(rec)
        return ok(h.public(rec))
