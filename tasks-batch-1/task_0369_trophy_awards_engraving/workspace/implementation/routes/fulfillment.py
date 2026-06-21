from flask import Blueprint
from db import db, now_iso
from errors import err
from response import ok, ok_list
from middleware import authenticate, require_role
from services import serialize, calc
from services.common import (
    get_json_body, stamp_create, touch, paginate, page_slice,
    require_fields, is_str, is_int,
)
from services.orders import get_order_or_404, enforce_order_ownership
from services import pricing

bp = Blueprint("fulfillment", __name__)


@bp.route("/orders/<order_id>/fulfillments", methods=["POST"])
def stage_fulfillment(order_id):
    caller = authenticate()
    require_role(caller, ("ShopStaff",))
    o = get_order_or_404(order_id)
    body = get_json_body()
    require_fields(body, ["method"])
    method = body["method"]
    if method not in ("PICKUP", "SHIP"):
        raise err("ERR_INVALID_REQUEST", "method must be PICKUP or SHIP")
    ship_address = body.get("ship_address")
    ship_weight = body.get("ship_weight_grams", 0)
    if ship_address is not None and not is_str(ship_address):
        raise err("ERR_INVALID_REQUEST", "ship_address must be a string")
    if not is_int(ship_weight) or ship_weight < 0:
        raise err("ERR_INVALID_REQUEST", "ship_weight_grams must be an integer >= 0")

    if o["production_status"] != "READY":
        raise err("ERR_INVALID_STATE", "Order must be READY to stage a fulfillment")

    ship_fee = 0
    if method == "SHIP":
        if not ship_address or ship_weight <= 0:
            raise err("ERR_SHIP_WEIGHT_REQUIRED",
                      "SHIP fulfillment requires ship_address and ship_weight_grams > 0")
        ship_fee = calc.ship_fee(ship_weight)

    rec = {
        "order_id": order_id,
        "method": method,
        "ship_address": ship_address,
        "ship_fee_cents": ship_fee,
        "ship_weight_grams": ship_weight,
        "fulfillment_status": "STAGED",
        "handed_off_at": None,
    }
    stamp_create(rec)
    db.fulfillments[rec["id"]] = rec
    return ok(serialize.fulfillment(rec), 201)


@bp.route("/orders/<order_id>/fulfillments", methods=["GET"])
def list_fulfillments(order_id):
    caller = authenticate()
    require_role(caller, ("Customer", "ShopStaff", "ShopManager"))
    o = get_order_or_404(order_id)
    enforce_order_ownership(caller, o)
    items = [f for f in db.fulfillments.values() if f["order_id"] == order_id]
    limit, offset = paginate()
    page, total = page_slice(items, limit, offset)
    return ok_list([serialize.fulfillment(f) for f in page], limit, offset, total)


@bp.route("/orders/<order_id>/fulfillments/<fid>/hand-off", methods=["POST"])
def hand_off(order_id, fid):
    caller = authenticate()
    require_role(caller, ("ShopStaff",))
    o = get_order_or_404(order_id)
    f = db.fulfillments.get(fid)
    if f is None or f["order_id"] != order_id:
        raise err("ERR_NOT_FOUND", "Fulfillment not found")

    if f["fulfillment_status"] != "STAGED" or o["production_status"] != "READY":
        raise err("ERR_INVALID_STATE", "Fulfillment must be STAGED and order READY to hand off")
    if o["payment_status"] != "PAID_IN_FULL":
        raise err("ERR_BALANCE_DUE", "Order must be paid in full before hand-off")

    ts = now_iso()
    f["fulfillment_status"] = "HANDED_OFF"
    f["handed_off_at"] = ts
    touch(f)

    # Order READY -> FULFILLED
    o["fulfilled_at"] = ts
    due = pricing.parse_due(o["due_date"])
    fulfilled = pricing.parse_due(ts)
    o["due_date_met"] = (fulfilled.date() <= due.date())
    o["production_status"] = "FULFILLED"
    touch(o)

    # Customer counters
    cust = db.customers.get(o["customer_id"])
    if cust is not None:
        cust["lifetime_completed_orders"] += 1
        fulfilled_orders = [ord_ for ord_ in db.orders.values()
                            if ord_["customer_id"] == cust["id"]
                            and ord_["production_status"] == "FULFILLED"]
        cust["on_time_rate_pct"] = calc.on_time_rate(fulfilled_orders)
        touch(cust)

    return ok(serialize.fulfillment(f))
