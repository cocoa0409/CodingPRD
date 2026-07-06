"""Stores, menu items, modifiers, pickup slots."""
from flask import Blueprint

from db import db
from errors import err
from helpers import (body, require_fields, require_str, require_int, require_bool,
                     validate_allergen_array, validate_enum, get_or_404, fk_or_404,
                     paginate, filter_by, ALLERGENS)
from middleware import get_auth, require_roles
from response import success
from serializers import serialize
from services.queue import recompute_queue_status

bp = Blueprint("catalog", __name__)

CHANNELS = {"COUNTER", "LOCKER", "DELIVERY"}


# ---------------- Stores ----------------
@bp.post("/stores")
def create_store():
    # public bootstrap endpoint — no auth required
    data = body()
    require_fields(data, ["name", "state_code", "throughput_capacity_per_slot"])
    require_str(data, "name")
    require_str(data, "state_code")
    require_int(data, "throughput_capacity_per_slot")
    require_int(data, "locker_count")
    require_bool(data, "is_active")
    if data["throughput_capacity_per_slot"] < 1:
        raise err("ERR_INVALID_REQUEST", "throughput_capacity_per_slot must be >= 1.")
    locker_count = data.get("locker_count", 0)
    if locker_count is None:
        locker_count = 0
    if locker_count < 0:
        raise err("ERR_INVALID_REQUEST", "locker_count must be >= 0.")
    is_active = data.get("is_active", True)
    if is_active is None:
        is_active = True

    store = db.common_fields()
    store.update({
        "name": data["name"],
        "state_code": data["state_code"],
        "throughput_capacity_per_slot": data["throughput_capacity_per_slot"],
        "locker_count": locker_count,
        "queue_status": "OPEN",  # newly created store begins OPEN (§2.7)
        "is_active": is_active,
    })
    db.stores[store["id"]] = store
    return success(serialize("store", store), 201)


@bp.get("/stores/<sid>")
def get_store(sid):
    get_auth()
    store = get_or_404("store", sid)
    return success(serialize("store", store), 200)


# ---------------- Menu items ----------------
@bp.post("/menu-items")
def create_menu_item():
    _, role = get_auth()
    require_roles(role, {"PlatformAdmin"})
    data = body()
    require_fields(data, ["store_id", "name", "base_price_cents", "base_calories"])
    require_str(data, "store_id")
    require_str(data, "name")
    require_int(data, "base_price_cents")
    require_int(data, "base_calories")
    validate_allergen_array(data, "allergen_tags")
    require_bool(data, "is_available")
    fk_or_404("store", data["store_id"])
    if data["base_price_cents"] < 0:
        raise err("ERR_INVALID_REQUEST", "base_price_cents must be >= 0.")
    if data["base_calories"] < 0:
        raise err("ERR_INVALID_REQUEST", "base_calories must be >= 0.")
    is_available = data.get("is_available", True)
    if is_available is None:
        is_available = True

    item = db.common_fields()
    item.update({
        "store_id": data["store_id"],
        "name": data["name"],
        "base_price_cents": data["base_price_cents"],
        "base_calories": data["base_calories"],
        "allergen_tags": data.get("allergen_tags") or [],
        "is_available": is_available,
    })
    db.menu_items[item["id"]] = item
    return success(serialize("menu_item", item), 201)


@bp.get("/menu-items/<mid>")
def get_menu_item(mid):
    get_auth()
    item = get_or_404("menu_item", mid)
    return success(serialize("menu_item", item), 200)


@bp.get("/menu-items")
def list_menu_items():
    get_auth()
    from flask import request
    store_id = request.args.get("store_id")
    items = filter_by(db.menu_items, store_id=store_id)
    page, meta = paginate(items)
    return success([serialize("menu_item", i) for i in page], 200, meta)


# ---------------- Modifiers ----------------
@bp.post("/modifiers")
def create_modifier():
    _, role = get_auth()
    require_roles(role, {"PlatformAdmin"})
    data = body()
    require_fields(data, ["menu_item_id", "name", "price_delta_cents", "calorie_delta"])
    require_str(data, "menu_item_id")
    require_str(data, "name")
    require_int(data, "price_delta_cents")
    require_int(data, "calorie_delta")
    validate_allergen_array(data, "adds_allergen_tags")
    fk_or_404("menu_item", data["menu_item_id"])

    mod = db.common_fields()
    mod.update({
        "menu_item_id": data["menu_item_id"],
        "name": data["name"],
        "price_delta_cents": data["price_delta_cents"],
        "calorie_delta": data["calorie_delta"],
        "adds_allergen_tags": data.get("adds_allergen_tags") or [],
    })
    db.modifiers[mod["id"]] = mod
    return success(serialize("modifier", mod), 201)


@bp.get("/modifiers/<mid>")
def get_modifier(mid):
    get_auth()
    mod = get_or_404("modifier", mid)
    return success(serialize("modifier", mod), 200)


@bp.get("/modifiers")
def list_modifiers():
    get_auth()
    from flask import request
    menu_item_id = request.args.get("menu_item_id")
    mods = filter_by(db.modifiers, menu_item_id=menu_item_id)
    page, meta = paginate(mods)
    return success([serialize("modifier", m) for m in page], 200, meta)


# ---------------- Pickup slots ----------------
@bp.post("/pickup-slots")
def create_pickup_slot():
    _, role = get_auth()
    require_roles(role, {"PlatformAdmin", "StoreManager"})
    data = body()
    require_fields(data, ["store_id", "window_start_utc", "window_end_utc", "channel"])
    require_str(data, "store_id")
    require_str(data, "window_start_utc")
    require_str(data, "window_end_utc")
    validate_enum(data, "channel", CHANNELS)
    fk_or_404("store", data["store_id"])

    slot = db.common_fields()
    slot.update({
        "store_id": data["store_id"],
        "window_start_utc": data["window_start_utc"],
        "window_end_utc": data["window_end_utc"],
        "channel": data["channel"],
        "reserved_count": 0,
        "is_closed": False,
    })
    db.pickup_slots[slot["id"]] = slot
    return success(serialize("pickup_slot", slot), 201)


@bp.get("/pickup-slots/<sid>")
def get_pickup_slot(sid):
    get_auth()
    slot = get_or_404("pickup_slot", sid)
    return success(serialize("pickup_slot", slot), 200)


@bp.get("/pickup-slots")
def list_pickup_slots():
    get_auth()
    from flask import request
    store_id = request.args.get("store_id")
    slots = filter_by(db.pickup_slots, store_id=store_id)
    page, meta = paginate(slots)
    return success([serialize("pickup_slot", s) for s in page], 200, meta)


@bp.post("/pickup-slots/<sid>/close")
def close_pickup_slot(sid):
    _, role = get_auth()
    require_roles(role, {"PlatformAdmin", "StoreManager"})
    slot = get_or_404("pickup_slot", sid)
    slot["is_closed"] = True
    db.touch(slot)  # increments version by 1
    store = db.stores.get(slot["store_id"])
    if store:
        recompute_queue_status(store)
    return success(serialize("pickup_slot", slot), 200)
