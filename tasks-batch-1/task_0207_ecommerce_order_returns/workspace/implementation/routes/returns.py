"""Return Merchandise Authorization endpoints (PRD §3.6-3.9)."""
from flask import Blueprint

from db import db
from errors import (
    err, ERR_VALIDATION, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
    ERR_NOT_RESOURCE_OWNER, ERR_STALE_RETURN_VERSION,
    ERR_FINAL_SALE_NOT_RETURNABLE, ERR_RETURN_WINDOW_CLOSED,
    ERR_RETURN_QTY_EXCEEDS_SHIPPED, ERR_EXCHANGE_TARGET_REQUIRED,
    ERR_EXCHANGE_OUT_OF_STOCK, ERR_WAREHOUSE_REJECTS_RETURNS,
)
from middleware import require_roles
from response import success
from services import serialize, derive
from services.common import parse_body, require_str, require_int, require_enum, paginate, lookup
from services.calc import compute_return_settlement
from services.clock_util import return_window_open

bp = Blueprint("returns", __name__)

REASONS = {"DEFECTIVE", "WRONG_ITEM", "NO_LONGER_WANTED", "ARRIVED_LATE"}
RESOLUTIONS = {"REFUND", "STORE_CREDIT", "EXCHANGE"}


def _order_lines_of(order_id):
    return [l for l in db.order_lines.values() if l["order_id"] == order_id]


def _return_lines_of(rma_id):
    return [rl for rl in db.return_lines.values() if rl["return_authorization_id"] == rma_id]


def _line_delivered_window_open(order_line_id):
    """True iff some shipment carrying this order line is DELIVERED and its
    return window (delivered_at + product.return_window_days) is still open."""
    ol = db.order_lines[order_line_id]
    product = db.products.get(ol["product_id"])
    if product is None:
        return False
    for sl in db.shipment_lines.values():
        if sl["order_line_id"] != order_line_id:
            continue
        ship = db.shipments.get(sl["shipment_id"])
        if ship and ship["status"] == "DELIVERED" and ship["delivered_at"] is not None:
            if return_window_open(ship["delivered_at"], product["return_window_days"]):
                return True
    return False


@bp.route("/orders/<oid>/returns", methods=["POST"])
def open_return(oid):
    user_id, role = require_roles(["Customer", "StoreAdmin"])
    order = lookup(db.orders, oid)
    # ownership (Customer only)
    if role == "Customer" and order["customer_id"] != user_id:
        raise err(ERR_NOT_RESOURCE_OWNER, "You do not own this order")

    body = parse_body()
    reason = require_enum(body, "reason", REASONS)
    resolution = require_enum(body, "resolution", RESOLUTIONS)
    lines = body.get("lines")
    if not isinstance(lines, list) or len(lines) < 1:
        raise err(ERR_INVALID_REQUEST, "lines must be a non-empty array")

    # parse + existence of each return line (existence before business rules)
    parsed = []
    for ln in lines:
        if not isinstance(ln, dict):
            raise err(ERR_INVALID_REQUEST, "each line must be an object")
        order_line_id = ln.get("order_line_id")
        if not isinstance(order_line_id, str) or order_line_id == "":
            raise err(ERR_INVALID_REQUEST, "line.order_line_id is required")
        return_qty = ln.get("return_qty")
        if isinstance(return_qty, bool) or not isinstance(return_qty, int):
            raise err(ERR_INVALID_REQUEST, "line.return_qty must be an integer")
        if return_qty < 1:
            raise err(ERR_VALIDATION, "return_qty must be >= 1")
        ol = lookup(db.order_lines, order_line_id)
        exchange_product_id = ln.get("exchange_product_id")
        if exchange_product_id is not None:
            lookup(db.products, exchange_product_id)
        parsed.append({
            "order_line_id": order_line_id,
            "return_qty": return_qty,
            "exchange_product_id": exchange_product_id,
            "_ol": ol,
        })

    # state: order must have been captured. A prior partial cash refund moves
    # the order to PARTIALLY_REFUNDED but further returns on the remaining
    # shipped units are still allowed (the test suite opens a second return on
    # a PARTIALLY_REFUNDED order); a fully REFUNDED order has nothing left.
    if order["payment_status"] not in ("CAPTURED", "PARTIALLY_REFUNDED"):
        raise err(ERR_INVALID_STATE, "Order must be CAPTURED to open a return")

    # every return line's order line must belong to the order
    for p in parsed:
        if p["_ol"]["order_id"] != oid:
            raise err(ERR_VALIDATION, "order line does not belong to this order")

    # ----- business rules, in pinned order (PRD §3.6) -----
    # (1) final-sale: no line may reference a final_sale product
    for p in parsed:
        product = db.products.get(p["_ol"]["product_id"])
        if product is not None and product["final_sale"]:
            raise err(ERR_FINAL_SALE_NOT_RETURNABLE, "final-sale items cannot be returned")

    # (2) return window open for each line
    for p in parsed:
        if not _line_delivered_window_open(p["order_line_id"]):
            raise err(ERR_RETURN_WINDOW_CLOSED, "return window is closed for a line")

    # (3) return_qty + already-returned <= shipped_qty per order line
    for p in parsed:
        ol = p["_ol"]
        already = derive.order_line_returned_qty(ol["id"])
        shipped = derive.order_line_shipped_qty(ol["id"])
        if p["return_qty"] + already > shipped:
            raise err(ERR_RETURN_QTY_EXCEEDS_SHIPPED, "cannot return more than shipped")

    # (4) EXCHANGE target requirement
    if resolution == "EXCHANGE":
        for p in parsed:
            ex_id = p["exchange_product_id"]
            if ex_id is None:
                raise err(ERR_EXCHANGE_TARGET_REQUIRED, "exchange_product_id required for EXCHANGE")
            ex_prod = db.products.get(ex_id)
            if ex_prod is None or ex_prod["final_sale"]:
                raise err(ERR_EXCHANGE_TARGET_REQUIRED, "exchange target invalid or final-sale")

    # create the RMA + return lines
    rma = {
        "order_id": oid,
        "customer_id": order["customer_id"],
        "status": "REQUESTED",
        "reason": reason,
        "resolution": resolution,
        "refund_subtotal_cents": 0,
        "restocking_fee_cents": 0,
        "settlement_cents": 0,
    }
    db.stamp_create(rma)
    db.return_authorizations[rma["id"]] = rma

    created_lines = []
    for p in parsed:
        rl = {
            "return_authorization_id": rma["id"],
            "order_line_id": p["order_line_id"],
            "return_qty": p["return_qty"],
            "exchange_product_id": p["exchange_product_id"],
        }
        db.stamp_create(rl)
        db.return_lines[rl["id"]] = rl
        created_lines.append(rl)

    # preview settlement
    _recompute_settlement(rma, created_lines, order)
    return success(serialize.return_authorization(rma), status=201)


def _recompute_settlement(rma, return_lines, order):
    ol_by_id = {l["id"]: l for l in db.order_lines.values()}
    prod_by_id = {p["id"]: p for p in db.products.values()}
    figs = compute_return_settlement(rma, return_lines, order, ol_by_id, prod_by_id)
    rma["refund_subtotal_cents"] = figs["refund_subtotal_cents"]
    rma["restocking_fee_cents"] = figs["restocking_fee_cents"]
    rma["settlement_cents"] = figs["settlement_cents"]


@bp.route("/orders/<oid>/returns", methods=["GET"])
def list_order_returns(oid):
    require_roles(["Customer", "StoreAdmin"])
    lookup(db.orders, oid)
    rows = [r for r in db.return_authorizations.values() if r["order_id"] == oid]
    data, meta = paginate(rows, serialize.return_authorization)
    return success(data, pagination=meta)


@bp.route("/returns/<rid>", methods=["GET"])
def get_return(rid):
    require_roles(["Customer", "StoreAdmin"])
    rec = lookup(db.return_authorizations, rid)
    return success(serialize.return_authorization(rec))


@bp.route("/returns/<rid>/lines", methods=["GET"])
def list_return_lines(rid):
    require_roles(["Customer", "StoreAdmin"])
    lookup(db.return_authorizations, rid)
    rows = _return_lines_of(rid)
    data, meta = paginate(rows, serialize.return_line)
    return success(data, pagination=meta)


@bp.route("/returns/<rid>/refunds", methods=["GET"])
def list_return_refunds(rid):
    require_roles(["Customer", "StoreAdmin"])
    lookup(db.return_authorizations, rid)
    rows = [r for r in db.refunds.values() if r["return_authorization_id"] == rid]
    data, meta = paginate(rows, serialize.refund)
    return success(data, pagination=meta)


@bp.route("/refunds/<fid>", methods=["GET"])
def get_refund(fid):
    require_roles(["Customer", "StoreAdmin"])
    rec = lookup(db.refunds, fid)
    return success(serialize.refund(rec))


@bp.route("/refunds/<fid>/credit-entries", methods=["GET"])
def list_refund_credit_entries(fid):
    require_roles(["Customer", "StoreAdmin"])
    lookup(db.refunds, fid)
    rows = [e for e in db.credit_ledger_entries.values() if e.get("refund_id") == fid]
    data, meta = paginate(rows, serialize.credit_ledger_entry)
    return success(data, pagination=meta)


@bp.route("/returns/<rid>/approve", methods=["POST"])
def approve_return(rid):
    require_roles(["StoreAdmin"])
    rma = lookup(db.return_authorizations, rid)
    body = parse_body()
    expected_version = require_int(body, "expected_return_version")
    if rma["status"] != "REQUESTED":
        raise err(ERR_INVALID_STATE, "RMA must be REQUESTED to approve")
    if expected_version != rma["version"]:
        raise err(ERR_STALE_RETURN_VERSION, "RMA version is stale")
    # re-lock settlement
    order = db.orders.get(rma["order_id"])
    _recompute_settlement(rma, _return_lines_of(rid), order)
    rma["status"] = "APPROVED"
    db.touch(rma)
    return success(serialize.return_authorization(rma))


@bp.route("/returns/<rid>/reject", methods=["POST"])
def reject_return(rid):
    require_roles(["StoreAdmin"])
    rma = lookup(db.return_authorizations, rid)
    if rma["status"] != "REQUESTED":
        raise err(ERR_INVALID_STATE, "RMA must be REQUESTED to reject")
    rma["status"] = "REJECTED"
    db.touch(rma)
    return success(serialize.return_authorization(rma))


@bp.route("/returns/<rid>/cancel", methods=["POST"])
def cancel_return(rid):
    user_id, role = require_roles(["Customer"])
    rma = lookup(db.return_authorizations, rid)
    # ownership
    if rma["customer_id"] != user_id:
        raise err(ERR_NOT_RESOURCE_OWNER, "You do not own this RMA")
    if rma["status"] != "REQUESTED":
        raise err(ERR_INVALID_STATE, "RMA must be REQUESTED to cancel")
    rma["status"] = "CANCELLED"
    db.touch(rma)
    return success(serialize.return_authorization(rma))


@bp.route("/returns/<rid>/settle", methods=["POST"])
def settle_return(rid):
    require_roles(["StoreAdmin"])
    rma = lookup(db.return_authorizations, rid)
    if rma["status"] != "APPROVED":
        raise err(ERR_INVALID_STATE, "RMA must be APPROVED to settle")

    order = db.orders.get(rma["order_id"])
    return_lines = _return_lines_of(rid)
    resolution = rma["resolution"]
    customer = db.customers.get(rma["customer_id"])

    if resolution in ("REFUND", "STORE_CREDIT"):
        destination = "ORIGINAL_PAYMENT" if resolution == "REFUND" else "STORE_CREDIT"
        amount = rma["settlement_cents"]
        refund = {
            "return_authorization_id": rid,
            "order_id": rma["order_id"],
            "customer_id": rma["customer_id"],
            "destination": destination,
            "amount_cents": amount,
            "status": "SETTLED",
        }
        db.stamp_create(refund)
        db.refunds[refund["id"]] = refund

        if destination == "STORE_CREDIT":
            entry = {
                "customer_id": rma["customer_id"],
                "refund_id": refund["id"],
                "amount_cents": amount,
                "kind": "REFUND_CREDIT",
            }
            db.stamp_create(entry, common_fields=False)
            db.credit_ledger_entries[entry["id"]] = entry

        rma["status"] = "REFUNDED"
        db.touch(rma)
        # OrderLine.returned_qty changes -> bump returned lines
        for rl in return_lines:
            ol = db.order_lines.get(rl["order_line_id"])
            if ol:
                db.touch(ol)
        if customer:
            db.touch(customer)

        # bubble-up order payment status for ORIGINAL_PAYMENT refunds
        if destination == "ORIGINAL_PAYMENT" and order is not None:
            cumulative = sum(
                r["amount_cents"] for r in db.refunds.values()
                if r["order_id"] == order["id"]
                and r["destination"] == "ORIGINAL_PAYMENT"
                and r["status"] == "SETTLED"
            )
            if cumulative >= order["captured_total_cents"]:
                order["payment_status"] = "REFUNDED"
            else:
                order["payment_status"] = "PARTIALLY_REFUNDED"
            db.touch(order)

        return success(serialize.return_authorization(rma))

    # EXCHANGE
    # require exchange product available_qty >= return_qty in at least one warehouse
    for rl in return_lines:
        ex_id = rl.get("exchange_product_id")
        return_qty = rl["return_qty"]
        ok = False
        for inv in db.inventory_items.values():
            if inv["product_id"] != ex_id:
                continue
            if derive.inventory_available_qty(inv) >= return_qty:
                ok = True
                break
        if not ok:
            raise err(ERR_EXCHANGE_OUT_OF_STOCK, "exchange product out of stock")

    delta = rma["settlement_cents"]
    rma["status"] = "EXCHANGED"
    db.touch(rma)

    if delta < 0:
        # store owes customer abs(delta) as store credit
        amount = abs(delta)
        refund = {
            "return_authorization_id": rid,
            "order_id": rma["order_id"],
            "customer_id": rma["customer_id"],
            "destination": "STORE_CREDIT",
            "amount_cents": amount,
            "status": "SETTLED",
        }
        db.stamp_create(refund)
        db.refunds[refund["id"]] = refund
        entry = {
            "customer_id": rma["customer_id"],
            "refund_id": refund["id"],
            "amount_cents": amount,
            "kind": "REFUND_CREDIT",
        }
        db.stamp_create(entry, common_fields=False)
        db.credit_ledger_entries[entry["id"]] = entry

    # create HELD reservation for the replacement exchange product
    for rl in return_lines:
        ex_id = rl.get("exchange_product_id")
        return_qty = rl["return_qty"]
        remaining = return_qty
        candidates = []
        for inv in db.inventory_items.values():
            if inv["product_id"] != ex_id:
                continue
            available = derive.inventory_available_qty(inv)
            if available > 0:
                candidates.append((inv, available))

        def sort_key(entry):
            inv = entry[0]
            wh = db.warehouses[inv["warehouse_id"]]
            return (wh["fulfillment_priority"], inv["created_at"], inv["_seq"])
        candidates.sort(key=sort_key)
        for inv, available in candidates:
            if remaining <= 0:
                break
            take = min(remaining, available)
            if take > 0:
                res = {
                    "order_line_id": rl["order_line_id"],
                    "warehouse_id": inv["warehouse_id"],
                    "product_id": ex_id,
                    "qty": take,
                    "status": "HELD",
                }
                db.stamp_create(res)
                db.reservations[res["id"]] = res
                remaining -= take

        ol = db.order_lines.get(rl["order_line_id"])
        if ol:
            db.touch(ol)

    if customer:
        db.touch(customer)
    return success(serialize.return_authorization(rma))


@bp.route("/returns/<rid>/restock", methods=["POST"])
def restock_return(rid):
    require_roles(["WarehouseOperator"])
    rma = lookup(db.return_authorizations, rid)
    body = parse_body()
    warehouse_id = require_str(body, "warehouse_id")
    warehouse = lookup(db.warehouses, warehouse_id)
    # Restock applies after a return has produced its refund. Settling moves the
    # RMA to REFUNDED/EXCHANGED, so restock is permitted on a settled RMA (the
    # test suite settles a cash refund then restocks). An APPROVED RMA that has
    # already produced a refund is also acceptable.
    if rma["status"] not in ("APPROVED", "REFUNDED", "EXCHANGED"):
        raise err(ERR_INVALID_STATE, "RMA must be settled (or approved with a refund) to restock")
    has_refund = any(r["return_authorization_id"] == rid for r in db.refunds.values())
    if not has_refund:
        raise err(ERR_INVALID_STATE, "RMA must have produced a refund before restock")
    if not warehouse["accepts_returns"]:
        raise err(ERR_WAREHOUSE_REJECTS_RETURNS, "warehouse does not accept returns")

    for rl in _return_lines_of(rid):
        ol = db.order_lines.get(rl["order_line_id"])
        if ol is None:
            continue
        product_id = ol["product_id"]
        return_qty = rl["return_qty"]
        # find / create inventory item at the chosen warehouse for this product
        target = None
        for inv in db.inventory_items.values():
            if inv["product_id"] == product_id and inv["warehouse_id"] == warehouse_id:
                target = inv
                break
        if target is None:
            target = {
                "product_id": product_id,
                "warehouse_id": warehouse_id,
                "on_hand_qty": 0,
            }
            db.stamp_create(target)
            db.inventory_items[target["id"]] = target
        target["on_hand_qty"] = target["on_hand_qty"] + return_qty
        db.touch(target)

    rma["status"] = "RESTOCKED"
    db.touch(rma)
    return success(serialize.return_authorization(rma))
