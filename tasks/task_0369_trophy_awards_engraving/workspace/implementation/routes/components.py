from flask import Blueprint
from db import db
from errors import err
from response import ok, ok_list
from middleware import authenticate, require_role
from services import serialize
from services.common import (
    get_json_body, stamp_create, touch, paginate, page_slice,
    require_fields, is_str, is_int,
)
from services.inventory import recompute_component

bp = Blueprint("components", __name__)


@bp.route("/components", methods=["POST"])
def create_component():
    caller = authenticate()
    require_role(caller, ("ShopManager",))
    body = get_json_body()
    require_fields(body, ["code", "name", "on_hand_qty"])
    code = body["code"]
    name = body["name"]
    on_hand = body["on_hand_qty"]
    if not is_str(code) or not code.strip():
        raise err("ERR_INVALID_REQUEST", "code must be a non-empty string")
    if not is_str(name):
        raise err("ERR_INVALID_REQUEST", "name must be a string")
    if not is_int(on_hand) or on_hand < 0:
        raise err("ERR_INVALID_REQUEST", "on_hand_qty must be an integer >= 0")
    reorder_point = body.get("reorder_point", 0)
    if not is_int(reorder_point) or reorder_point < 0:
        raise err("ERR_INVALID_REQUEST", "reorder_point must be an integer >= 0")

    for c in db.components.values():
        if c["code"] == code:
            raise err("ERR_DUPLICATE_VALUE", "A component with this code already exists")

    rec = {
        "code": code,
        "name": name,
        "on_hand_qty": on_hand,
        "allocated_qty": 0,
        "available_qty": 0,
        "reorder_point": reorder_point,
        "low_stock": False,
    }
    stamp_create(rec)
    db.components[rec["id"]] = rec
    recompute_component(rec)
    return ok(serialize.component(rec), 201)


@bp.route("/components/<cid>", methods=["GET"])
def get_component(cid):
    caller = authenticate()
    require_role(caller, ("ShopStaff", "ShopManager"))
    rec = db.components.get(cid)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Component not found")
    return ok(serialize.component(rec))


@bp.route("/components/<cid>/receive", methods=["POST"])
def receive_component(cid):
    caller = authenticate()
    require_role(caller, ("ShopManager",))
    rec = db.components.get(cid)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Component not found")
    body = get_json_body()
    require_fields(body, ["received_qty"])
    qty = body["received_qty"]
    if not is_int(qty) or qty < 1:
        raise err("ERR_INVALID_REQUEST", "received_qty must be an integer >= 1")
    rec["on_hand_qty"] += qty
    recompute_component(rec)
    touch(rec)
    return ok(serialize.component(rec))


# ----- ComponentAllocation reads -----

@bp.route("/order-lines/<line_id>/component-allocations", methods=["GET"])
def list_line_allocations(line_id):
    caller = authenticate()
    require_role(caller, ("ShopStaff", "ShopManager"))
    if line_id not in db.order_lines:
        raise err("ERR_NOT_FOUND", "Order line not found")
    items = [a for a in db.component_allocations.values() if a["order_line_id"] == line_id]
    limit, offset = paginate()
    page, total = page_slice(items, limit, offset)
    return ok_list([serialize.component_allocation(a) for a in page], limit, offset, total)


@bp.route("/component-allocations", methods=["GET"])
def list_allocations():
    caller = authenticate()
    require_role(caller, ("ShopStaff", "ShopManager"))
    from flask import request
    component_id = request.args.get("component_id")
    order_line_id = request.args.get("order_line_id")
    items = list(db.component_allocations.values())
    if component_id is not None:
        items = [a for a in items if a["component_id"] == component_id]
    if order_line_id is not None:
        items = [a for a in items if a["order_line_id"] == order_line_id]
    limit, offset = paginate()
    page, total = page_slice(items, limit, offset)
    return ok_list([serialize.component_allocation(a) for a in page], limit, offset, total)


@bp.route("/component-allocations/<aid>", methods=["GET"])
def get_allocation(aid):
    caller = authenticate()
    require_role(caller, ("ShopStaff", "ShopManager"))
    rec = db.component_allocations.get(aid)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Component allocation not found")
    return ok(serialize.component_allocation(rec))
