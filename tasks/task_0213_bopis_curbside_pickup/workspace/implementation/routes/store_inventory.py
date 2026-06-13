"""StoreInventory endpoints."""

from flask import Blueprint, request

from db import db, stamp_common, touch
from errors import err
from middleware import require_auth, get_json_body
from response import object_response, array_response
from services.common import (
    require_str, require_nonneg_int, require_int, ref_or_404, get_or_404,
    parse_pagination, paginate, ser_inventory, ser_movement,
)
from services.inventory import recompute_available, append_movement, find_inventory

bp = Blueprint("store_inventory", __name__)


@bp.post("/store-inventory")
def create_inventory():
    require_auth({"PlatformAdmin", "StoreManager"})
    body = get_json_body()
    store_id = require_str(body, "store_id")
    product_id = require_str(body, "product_id")
    on_hand = require_nonneg_int(body, "on_hand")

    # FK existence (priority 5)
    ref_or_404(db.stores, store_id, "store")
    ref_or_404(db.products, product_id, "product")

    # uniqueness (priority 7)
    if find_inventory(store_id, product_id) is not None:
        raise err("ERR_DUPLICATE_INVENTORY",
                  "inventory already exists for this store/product")

    rec = {
        "store_id": store_id,
        "product_id": product_id,
        "on_hand": on_hand,
        "reserved": 0,
        "available": on_hand,
    }
    stamp_common(rec)
    db.store_inventory[rec["id"]] = rec
    # initial RESTOCK movement
    append_movement(rec, "RESTOCK", on_hand, 0, "MANUAL")
    return object_response(ser_inventory(rec), 201)


@bp.get("/store-inventory")
def list_inventory():
    require_auth({"Customer", "StorePicker", "StoreManager", "PlatformAdmin"})
    limit, offset = parse_pagination(request.args)
    store_id = request.args.get("store_id")
    product_id = request.args.get("product_id")
    items = list(db.store_inventory.values())
    if store_id is not None:
        items = [i for i in items if i["store_id"] == store_id]
    if product_id is not None:
        items = [i for i in items if i["product_id"] == product_id]
    page, total = paginate(items, limit, offset)
    return array_response([ser_inventory(i) for i in page], limit, offset, total)


@bp.get("/store-inventory/<iid>")
def get_inventory(iid):
    require_auth({"Customer", "StorePicker", "StoreManager", "PlatformAdmin"})
    rec = get_or_404(db.store_inventory, iid)
    return object_response(ser_inventory(rec))


@bp.get("/store-inventory/<iid>/movements")
def list_movements(iid):
    require_auth({"StoreManager", "PlatformAdmin"})
    get_or_404(db.store_inventory, iid)
    limit, offset = parse_pagination(request.args)
    items = [m for m in db.inventory_movements.values()
             if m["store_inventory_id"] == iid]
    page, total = paginate(items, limit, offset)
    return array_response([ser_movement(m) for m in page], limit, offset, total)


@bp.post("/store-inventory/<iid>/restock")
def restock_inventory(iid):
    require_auth({"PlatformAdmin", "StoreManager"})
    rec = get_or_404(db.store_inventory, iid)
    body = get_json_body()
    # required body fields present + well-typed (priority 6)
    delta_on_hand = require_int(body, "delta_on_hand")
    expected_inventory_version = require_int(body, "expected_inventory_version")

    # OCC (priority 9): mismatch -> ERR_STALE_INVENTORY_VERSION
    if expected_inventory_version != rec["version"]:
        raise err("ERR_STALE_INVENTORY_VERSION",
                  "expected_inventory_version does not match current version")

    new_on_hand = rec["on_hand"] + delta_on_hand
    if new_on_hand < 0:
        raise err("ERR_INVALID_REQUEST", "restock would drive on_hand below zero")
    rec["on_hand"] = new_on_hand
    recompute_available(rec)
    append_movement(rec, "RESTOCK", delta_on_hand, 0, "MANUAL")
    touch(rec)
    return object_response(ser_inventory(rec))
