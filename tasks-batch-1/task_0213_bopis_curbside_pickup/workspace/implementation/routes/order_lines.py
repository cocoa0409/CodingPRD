"""OrderLine picking endpoints + line-scoped reverse navigation."""

from flask import Blueprint, request

from db import db, touch
from errors import err
from middleware import require_auth, get_json_body
from response import object_response, array_response
from services.common import (
    require_nonneg_int, get_or_404, parse_pagination, paginate,
    ser_line, ser_pickup_event, ser_substitution,
)
from services import inventory as inv_svc

bp = Blueprint("order_lines", __name__)


@bp.get("/order-lines")
def list_order_lines():
    require_auth({"StorePicker", "StoreAssociate", "StoreManager", "PlatformAdmin"})
    limit, offset = parse_pagination(request.args)
    items = list(db.order_lines.values())
    for key in ("product_id", "order_id"):
        val = request.args.get(key)
        if val is not None:
            items = [ln for ln in items if ln.get(key) == val]
    page, total = paginate(items, limit, offset)
    return array_response([ser_line(l) for l in page], limit, offset, total)


@bp.get("/order-lines/<lid>")
def get_line(lid):
    require_auth({"Customer", "StorePicker", "StoreAssociate",
                  "StoreManager", "PlatformAdmin"})
    rec = get_or_404(db.order_lines, lid)
    return object_response(ser_line(rec))


@bp.get("/order-lines/<lid>/pickup-events")
def list_line_events(lid):
    require_auth({"Customer", "StoreAssociate", "StoreManager", "PlatformAdmin"})
    get_or_404(db.order_lines, lid)
    limit, offset = parse_pagination(request.args)
    items = [e for e in db.pickup_events.values() if e["order_line_id"] == lid]
    page, total = paginate(items, limit, offset)
    return array_response([ser_pickup_event(e) for e in page], limit, offset, total)


@bp.get("/order-lines/<lid>/substitutions")
def list_line_subs(lid):
    require_auth({"Customer", "StorePicker", "StoreManager", "PlatformAdmin"})
    get_or_404(db.order_lines, lid)
    limit, offset = parse_pagination(request.args)
    items = [s for s in db.substitutions.values() if s["order_line_id"] == lid]
    page, total = paginate(items, limit, offset)
    return array_response([ser_substitution(s) for s in page], limit, offset, total)


@bp.post("/order-lines/<lid>/pick")
def pick_line(lid):
    require_auth({"StorePicker"})
    line = get_or_404(db.order_lines, lid)
    body = get_json_body()
    qty_picked = require_nonneg_int(body, "qty_picked")
    order = db.orders.get(line["order_id"])

    # state guard (priority 8): parent order must be PICKING and line RESERVED
    if order is None or order["fulfillment_status"] != "PICKING" or \
            line["line_status"] != "RESERVED":
        raise err("ERR_INVALID_STATE", "line is not pickable in the current state")

    if qty_picked > line["qty_ordered"]:
        raise err("ERR_INVALID_REQUEST",
                  "qty_picked may not exceed qty_ordered")

    inv = inv_svc.find_inventory(order["store_id"], line["product_id"])
    on_hand = inv["on_hand"] if inv is not None else 0

    # on-hand requirement (priority 19)
    if on_hand < qty_picked:
        raise err("ERR_INSUFFICIENT_ON_HAND",
                  "insufficient on_hand for the requested pick")

    reason = "ORDER:%s" % order["id"]
    if qty_picked == line["qty_ordered"]:
        # full pick -> PICKED
        if inv is not None:
            inv_svc.pick_remove_full(inv, qty_picked, reason)
        line["qty_picked"] = qty_picked
        line["qty_reserved"] = 0
        line["line_status"] = "PICKED"
    else:
        # short pick (0 <= qty_picked < qty_ordered) -> SHORT_PICKED
        unpicked = line["qty_ordered"] - qty_picked
        if inv is not None:
            inv_svc.pick_remove_short(inv, qty_picked, unpicked, reason)
        line["qty_picked"] = qty_picked
        line["qty_reserved"] = qty_picked
        line["line_status"] = "SHORT_PICKED"
    touch(line)
    return object_response(ser_line(line))


@bp.post("/order-lines/<lid>/abandon")
def abandon_line(lid):
    require_auth({"StorePicker"})
    line = get_or_404(db.order_lines, lid)
    # state guard: must be SHORT_PICKED with nothing picked
    if line["line_status"] != "SHORT_PICKED":
        raise err("ERR_INVALID_STATE", "line is not SHORT_PICKED")
    if line["qty_picked"] != 0:
        raise err("ERR_INVALID_STATE",
                  "line may only be abandoned when nothing was picked")
    order = db.orders.get(line["order_id"])
    reason = "ORDER:%s" % line["order_id"]
    if line["qty_reserved"] > 0 and order is not None:
        inv = inv_svc.find_inventory(order["store_id"], line["product_id"])
        if inv is not None:
            inv_svc.release(inv, line["qty_reserved"], reason)
    line["qty_reserved"] = 0
    line["line_status"] = "NOT_FULFILLED"
    touch(line)
    return object_response(ser_line(line))
