"""OrderLine endpoints (PRD §3.6).

Per §3.6, a line referencing an UNLISTED item, or an item on another truck, is
rejected with ERR_MENU_ITEM_UNLISTED. FK existence of the menu item id itself is
checked first (priority 4) and yields ERR_MENU_ITEM_NOT_FOUND when the id is
unknown.
"""

from flask import request, Blueprint

import errors
import serializers
import services
from db import db
from errors import err
from helpers import get_body, require_str, require_fk, require_int, get_pagination, paginate
from lookups import get_order_line, get_order, get_menu_item
from middleware import require_user_context, require_role, require_truck_ownership
from response import ok_object, ok_array

bp = Blueprint("order_lines", __name__)

WRITE_ROLES = {"OperatorTruck", "PlatformAdmin"}
READ_ROLES = {"Dispatcher", "PlatformAdmin", "OperatorTruck", "HealthInspector"}


@bp.post("/order-lines")
def create_order_line():
    user_id, role = require_user_context()
    require_role(role, WRITE_ROLES)
    body = get_body()
    # FK existence (priority 4) before other well-formedness (priority 5).
    order_id = require_fk(body, "order_id")
    menu_item_id = require_fk(body, "menu_item_id")
    order = get_order(order_id)
    menu_item = get_menu_item(menu_item_id)
    # Ownership: owning truck is the order's truck.
    require_truck_ownership(user_id, role, order["truck_id"])
    quantity = require_int(body, "quantity", minimum=1)
    # Priority 6: order OPEN.
    if order["lifecycle_status"] != "OPEN":
        raise err(errors.ERR_ORDER_NOT_OPEN, "Order is not OPEN")
    # Priority 10: menu item AVAILABLE and on the order's truck.
    if menu_item["status"] != "AVAILABLE" or menu_item["truck_id"] != order["truck_id"]:
        raise err(errors.ERR_MENU_ITEM_UNLISTED,
                  "Menu item is UNLISTED or not on the order's truck")
    unit_price = menu_item["unit_price_cents"]
    rec = db.new_record({
        "order_id": order_id,
        "menu_item_id": menu_item_id,
        "quantity": quantity,
        "unit_price_cents": unit_price,
        "line_subtotal_cents": quantity * unit_price,
    })
    db.order_lines[rec["id"]] = rec
    # Recompute the parent order's live_total.
    order["live_total_cents"] = services.compute_live_total(order)
    db.touch(order)
    return ok_object(serializers.order_line(rec), 201)


@bp.get("/order-lines")
def list_order_lines():
    user_id, role = require_user_context()
    require_role(role, READ_ROLES)
    limit, offset = get_pagination()
    records = list(db.order_lines.values())
    for field in ("order_id", "menu_item_id"):
        val = request.args.get(field)
        if val is not None:
            records = [r for r in records if r[field] == val]
    window, total = paginate(records, limit, offset)
    return ok_array([serializers.order_line(r) for r in window], limit, offset, total)


@bp.get("/order-lines/<line_id>")
def get_order_line_route(line_id):
    user_id, role = require_user_context()
    require_role(role, READ_ROLES)
    rec = get_order_line(line_id)
    return ok_object(serializers.order_line(rec))
