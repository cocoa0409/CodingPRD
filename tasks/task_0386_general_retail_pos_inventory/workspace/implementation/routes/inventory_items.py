"""InventoryItem endpoints (PRD §3.1, §2.9)."""
from flask import Blueprint, request

from db import DB
from middleware import auth_context, require_role
from common import (
    stamp_create, public_view, get_json_body, as_int, as_str,
    parse_pagination, paginate,
)
from response import success, success_list
from errors import (
    err, ERR_NOT_FOUND, ERR_REFERENCE_NOT_FOUND, ERR_DUPLICATE_RESOURCE,
)
from services.inventory import find_item

bp = Blueprint("inventory_items", __name__)


@bp.route("/inventory-items", methods=["POST"])
def create_inventory_item():
    _, role = auth_context()
    require_role(role, {"InventoryClerk", "StoreManager"})
    body = get_json_body()
    store_id = as_str(body, "store_id")
    product_id = as_str(body, "product_id")
    # reorder_point/reorder_qty default 0 (PRD §3.1, scaffold defaults)
    reorder_point = as_int(body, "reorder_point", required=False, default=0, minimum=0)
    reorder_qty = as_int(body, "reorder_qty", required=False, default=0, minimum=0)

    with DB.lock:
        # body FK resolution (PRD §2.5, priority 4)
        if store_id not in DB.stores:
            raise err(ERR_REFERENCE_NOT_FOUND, "store_id not found")
        if product_id not in DB.products:
            raise err(ERR_REFERENCE_NOT_FOUND, "product_id not found")
        # uniqueness: at most one item per (store_id, product_id) (priority 6)
        if find_item(DB, store_id, product_id) is not None:
            raise err(ERR_DUPLICATE_RESOURCE, "Inventory item already exists for this store/product")
        item = {
            "store_id": store_id,
            "product_id": product_id,
            "on_hand_qty": 0,
            "reserved_qty": 0,
            "available_qty": 0,
            "reorder_point": reorder_point,
            "reorder_qty": reorder_qty,
            "below_reorder": (0 <= reorder_point),
        }
        stamp_create(item)
        DB.inventory_items[item["id"]] = item
        return success(public_view(item), status=201)


@bp.route("/inventory-items/<item_id>", methods=["GET"])
def get_inventory_item(item_id):
    _, role = auth_context()
    require_role(role, {"StoreManager", "Cashier", "InventoryClerk"})
    with DB.lock:
        item = DB.inventory_items.get(item_id)
        if item is None:
            raise err(ERR_NOT_FOUND, "Inventory item not found")
        return success(public_view(item))


@bp.route("/inventory-items", methods=["GET"])
def list_inventory_items():
    _, role = auth_context()
    require_role(role, {"StoreManager", "Cashier", "InventoryClerk"})
    limit, offset = parse_pagination()
    store_id = request.args.get("store_id")
    product_id = request.args.get("product_id")
    below_reorder = request.args.get("below_reorder")
    with DB.lock:
        recs = list(DB.inventory_items.values())
        if store_id is not None:
            recs = [r for r in recs if r["store_id"] == store_id]
        if product_id is not None:
            recs = [r for r in recs if r["product_id"] == product_id]
        if below_reorder is not None:
            want = below_reorder.lower() == "true"
            recs = [r for r in recs if r["below_reorder"] == want]
        items, total = paginate(recs, limit, offset)
        return success_list(items, limit, offset, total)
