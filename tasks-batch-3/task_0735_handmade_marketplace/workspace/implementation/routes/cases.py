"""Case endpoints — dispute lifecycle."""
from flask import Blueprint, request
from auth import get_auth, require_role, require_shop_owner, require_buyer_owner
from db import store, stamp_common, touch
from envelope import success
from errors import (
    raise_err, ERR_VALIDATION, ERR_CASE_NOT_FOUND, ERR_ORDER_NOT_FOUND,
    ERR_CASE_NOT_ALLOWED, ERR_INVALID_STATE, ERR_INVALID_RESOLUTION,
    ERR_NOT_SHOP_OWNER,
)
from helpers import get_json_body, require_field, opt_field, parse_pagination, paginate, sort_by_created
from serializers import case_view

bp = Blueprint("cases", __name__)

VALID_TYPES = {"NON_DELIVERY", "NOT_AS_DESCRIBED"}


def _order_has_open_case(order):
    for c in store.cases.values():
        if c["order_id"] == order["id"] and c["status"] in ("OPEN", "SELLER_RESPONDED", "ESCALATED"):
            return True
    return False


def _sync_order_open_case(order):
    order["has_open_case"] = _order_has_open_case(order)


@bp.route("/seller/cases", methods=["POST"])
def create():
    user_id, role = get_auth()
    require_role(role, {"Buyer"})
    body = get_json_body()
    order_id = require_field(body, "order_id", str)
    ctype = require_field(body, "type", str)

    order = store.orders.get(order_id)
    if order is None:
        raise_err(ERR_ORDER_NOT_FOUND, "order not found")

    if ctype not in VALID_TYPES:
        raise_err(ERR_VALIDATION, "invalid case type")

    reason = opt_field(body, "reason", str, None)

    # ERR_CASE_NOT_ALLOWED: order must be PAID and belong to acting buyer.
    if order["payment_status"] != "PAID" or order["buyer_id"] != user_id:
        raise_err(ERR_CASE_NOT_ALLOWED, "case not allowed")

    rec = {
        "order_id": order_id,
        "opener_buyer_id": user_id,
        "type": ctype,
        "status": "OPEN",
        "reason": reason,
        "resolution": None,
        "refund_amount_cents": 0,
    }
    stamp_common(rec)
    store.cases[rec["id"]] = rec

    # Mark order has_open_case
    order["has_open_case"] = True
    touch(order)

    # If order.payout_id set and its payout SCHEDULED, put payout ON_HOLD.
    pid = order.get("payout_id")
    if pid:
        p = store.payouts.get(pid)
        if p is not None and p["status"] == "SCHEDULED":
            p["status"] = "ON_HOLD"
            touch(p)

    return success(case_view(rec), status=201)


@bp.route("/seller/cases/<cid>", methods=["GET"])
def fetch(cid):
    user_id, role = get_auth()
    require_role(role, {"Seller", "PlatformAdmin", "Buyer"})
    c = store.cases.get(cid)
    if c is None:
        raise_err(ERR_CASE_NOT_FOUND, "not found")
    return success(case_view(c))


@bp.route("/seller/cases", methods=["GET"])
def list_():
    user_id, role = get_auth()
    require_role(role, {"Seller", "PlatformAdmin", "Buyer"})
    limit, offset = parse_pagination()
    args = request.args
    order_id = args.get("order_id")
    status = args.get("status")
    ctype = args.get("type")

    items = list(store.cases.values())
    if order_id is not None:
        items = [x for x in items if x["order_id"] == order_id]
    if status is not None:
        items = [x for x in items if x["status"] == status]
    if ctype is not None:
        items = [x for x in items if x["type"] == ctype]
    # Scope by acting role.
    if role == "Seller":
        # Sellers see cases on their orders.
        items = [x for x in items if store.orders.get(x["order_id"], {}).get("shop_id") == user_id]
    elif role == "Buyer":
        items = [x for x in items if x["opener_buyer_id"] == user_id]
    items = sort_by_created(items)
    page, pmeta = paginate(items, limit, offset)
    return success([case_view(x) for x in page], response_type="array", pagination=pmeta)


@bp.route("/seller/cases/<cid>/respond", methods=["POST"])
def respond(cid):
    user_id, role = get_auth()
    require_role(role, {"Seller"})
    c = store.cases.get(cid)
    if c is None:
        raise_err(ERR_CASE_NOT_FOUND, "not found")
    order = store.orders.get(c["order_id"])
    require_shop_owner(user_id, role, order["shop_id"])
    if c["status"] != "OPEN":
        raise_err(ERR_INVALID_STATE, "case not OPEN")
    body = get_json_body()
    # message is optional per endpoint spec
    _ = opt_field(body, "message", str, None)
    c["status"] = "SELLER_RESPONDED"
    touch(c)
    return success(case_view(c))


@bp.route("/seller/cases/<cid>/escalate", methods=["POST"])
def escalate(cid):
    user_id, role = get_auth()
    require_role(role, {"Buyer"})
    c = store.cases.get(cid)
    if c is None:
        raise_err(ERR_CASE_NOT_FOUND, "not found")
    if c["opener_buyer_id"] != user_id:
        # PRD: escalate is a buyer action; the acting buyer must have opened the case.
        raise_err(ERR_NOT_SHOP_OWNER, "buyer did not open this case")
    if c["status"] not in ("OPEN", "SELLER_RESPONDED"):
        raise_err(ERR_INVALID_STATE, "case not in OPEN or SELLER_RESPONDED")
    c["status"] = "ESCALATED"
    touch(c)
    return success(case_view(c))


@bp.route("/seller/cases/<cid>/resolve", methods=["POST"])
def resolve(cid):
    user_id, role = get_auth()
    require_role(role, {"Seller", "PlatformAdmin"})
    c = store.cases.get(cid)
    if c is None:
        raise_err(ERR_CASE_NOT_FOUND, "not found")
    order = store.orders.get(c["order_id"])
    # Ownership: seller resolving must own the order's shop.
    if role == "Seller":
        require_shop_owner(user_id, role, order["shop_id"])

    # State first (§3.8 PRD): ERR_INVALID_STATE before ERR_INVALID_RESOLUTION.
    if role == "Seller":
        if c["status"] != "SELLER_RESPONDED":
            raise_err(ERR_INVALID_STATE, "seller can only resolve SELLER_RESPONDED")
    else:  # PlatformAdmin
        if c["status"] != "ESCALATED":
            raise_err(ERR_INVALID_STATE, "admin can only resolve ESCALATED")

    body = get_json_body()
    decision = body.get("decision")
    resolution = opt_field(body, "resolution", str, None)
    if decision not in ("REFUND", "NO_REFUND"):
        raise_err(ERR_INVALID_RESOLUTION, "decision must be REFUND or NO_REFUND")

    if decision == "REFUND":
        c["status"] = "RESOLVED_REFUND"
        c["refund_amount_cents"] = order["order_total_cents"]
        c["resolution"] = resolution
        order["refunded_cents"] = order.get("refunded_cents", 0) + order["order_total_cents"]
        order["payment_status"] = "REFUNDED"
        touch(order)
    else:
        c["status"] = "RESOLVED_NO_REFUND"
        c["resolution"] = resolution

    touch(c)
    _sync_order_open_case(order)
    touch(order)
    return success(case_view(c))
