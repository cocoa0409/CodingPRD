"""Component item and component order endpoints."""
from flask import Blueprint, request

from db import db
from errors import raise_err
from middleware import get_auth, require_role
from response import success_response, parse_pagination, apply_pagination
from services.common import new_entity, touch, get_component_item, get_order
from services.serializers import serialize_component_item, serialize_component_order
from services.sweeps import allocation_sweep

bp = Blueprint("items", __name__)

ITEM_ROLES = {"ShopManager", "FittingSpecialist", "RepairTechnician"}
ORDER_ROLES = {"ShopManager", "FittingSpecialist"}
COMPONENT_TYPES = {"HEAD", "SHAFT", "GRIP"}


def _body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


@bp.post("/component-items")
def create_item():
    user_id, role = get_auth()
    require_role(role, {"ShopManager", "ShopAdmin"})
    data = _body()
    sku = data.get("sku")
    component_type = data.get("component_type")
    unit_cost_cents = data.get("unit_cost_cents")
    msrp_cents = data.get("msrp_cents")
    initial_stock = data.get("initial_stock")
    if not isinstance(sku, str) or not sku.strip():
        raise_err("ERR_VALIDATION", "sku is required")
    if component_type not in COMPONENT_TYPES:
        raise_err("ERR_VALIDATION", "invalid component_type")
    for field, val in (("unit_cost_cents", unit_cost_cents),
                       ("msrp_cents", msrp_cents),
                       ("initial_stock", initial_stock)):
        if not isinstance(val, int) or isinstance(val, bool):
            raise_err("ERR_VALIDATION", f"{field} must be an integer")
    for existing in db.component_items.values():
        if existing["sku"] == sku:
            raise_err("ERR_VALIDATION", "sku must be unique")
    i = new_entity()
    i.update({
        "sku": sku,
        "component_type": component_type,
        "unit_cost_cents": unit_cost_cents,
        "msrp_cents": msrp_cents,
        "stock_on_hand": initial_stock,
        "stock_reserved": 0,
        "consumed_total": 0,
        "received_total": initial_stock,
    })
    db.component_items[i["id"]] = i
    return success_response(serialize_component_item(i), status=201)


@bp.get("/component-items/<iid>")
def read_item(iid):
    user_id, role = get_auth()
    require_role(role, ITEM_ROLES)
    i = get_component_item(iid)
    return success_response(serialize_component_item(i))


@bp.get("/component-items")
def list_items():
    user_id, role = get_auth()
    require_role(role, ITEM_ROLES)
    limit, offset = parse_pagination(request.args)
    items = list(db.component_items.values())
    val = request.args.get("component_type")
    if val is not None:
        items = [i for i in items if i["component_type"] == val]
    items.sort(key=lambda i: i["created_at"])
    page, pagination = apply_pagination(items, limit, offset)
    return success_response(
        [serialize_component_item(i) for i in page],
        response_type="array", pagination=pagination,
    )


@bp.post("/component-items/<iid>/receive")
def receive_item(iid):
    user_id, role = get_auth()
    require_role(role, {"ShopManager"})
    data = _body()
    qty = data.get("qty")
    if not isinstance(qty, int) or isinstance(qty, bool) or qty < 1:
        raise_err("ERR_VALIDATION", "qty must be a positive integer")
    i = get_component_item(iid)
    i["stock_on_hand"] += qty
    i["received_total"] += qty
    touch(i)
    allocation_sweep()
    return success_response(serialize_component_item(i))


@bp.get("/component-orders/<oid>")
def read_order(oid):
    user_id, role = get_auth()
    require_role(role, ORDER_ROLES)
    o = get_order(oid)
    return success_response(serialize_component_order(o))


@bp.get("/component-orders")
def list_orders():
    user_id, role = get_auth()
    require_role(role, ORDER_ROLES)
    limit, offset = parse_pagination(request.args)
    items = list(db.component_orders.values())
    for field in ("build_spec_id", "status"):
        val = request.args.get(field)
        if val is not None:
            items = [o for o in items if o.get(field) == val]
    items.sort(key=lambda o: o["created_at"])
    page, pagination = apply_pagination(items, limit, offset)
    return success_response(
        [serialize_component_order(o) for o in page],
        response_type="array", pagination=pagination,
    )
