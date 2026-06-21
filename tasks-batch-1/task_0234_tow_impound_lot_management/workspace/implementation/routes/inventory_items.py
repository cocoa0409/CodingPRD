"""InventoryItem endpoints (nested under tow orders)."""
from flask import Blueprint, request

import db
from errors import ApiError
from middleware import get_json_body, require_role, require_user_context
from response import object_response
from services.serialize import public
from validators import paginate_and_respond, require_enum, require_str, sort_by_created

bp = Blueprint("inventory_items", __name__)

CATEGORIES = {"PERSONAL_PROPERTY", "VEHICLE_DAMAGE", "EXTERIOR_PHOTO"}


def get_order_or_404(order_id):
    o = db.tow_orders.get(order_id)
    if o is None:
        raise ApiError("ERR_NOT_FOUND", "Tow order not found")
    return o


@bp.route("/tow-orders/<order_id>/inventory-items", methods=["POST"])
def create_inventory(order_id):
    user_id, role = require_user_context()
    require_role(role, {"LotOperator"})
    get_order_or_404(order_id)
    body = get_json_body()
    category = require_enum(body, "category", CATEGORIES)
    description = require_str(body, "description")
    photo_ref = require_str(body, "photo_ref")
    condition_note = body.get("condition_note")
    if condition_note is not None and not isinstance(condition_note, str):
        raise ApiError("ERR_INVALID_REQUEST", "condition_note must be a string")
    item = {
        "tow_order_id": order_id,
        "category": category,
        "description": description,
        "photo_ref": photo_ref,
        "condition_note": condition_note,
    }
    db.stamp_create(item)
    db.inventory_items[item["id"]] = item
    return object_response(public(item), 201)


@bp.route("/tow-orders/<order_id>/inventory-items", methods=["GET"])
def list_inventory(order_id):
    user_id, role = require_user_context()
    require_role(role, {"LotOperator", "Claimant"})
    get_order_or_404(order_id)
    items = [i for i in db.inventory_items.values() if i["tow_order_id"] == order_id]
    category = request.args.get("category")
    if category is not None:
        items = [i for i in items if i["category"] == category]
    items = sort_by_created(items)
    return paginate_and_respond([public(i) for i in items])
