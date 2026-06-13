"""Stores, menu items, modifier options, pickup slots, and the test clock."""
from flask import Blueprint, request

import errors
import helpers
from db import db, new_id, iso_now
from clock import clock
from middleware import authenticate, require_roles
from response import success_object, success_array
from services import serializers

bp = Blueprint("catalog", __name__)


# ---------------- Stores ----------------
@bp.route("/stores", methods=["POST"])
def create_store():
    principal = authenticate()
    require_roles(principal, ["PlatformAdmin"])
    body = helpers.get_json_body()
    helpers.require_fields(body, ["name", "timezone", "slot_capacity", "prep_minutes"])
    name = helpers.require_str(body["name"], "name")
    tz = helpers.require_str(body["timezone"], "timezone")
    slot_capacity = helpers.require_int(body["slot_capacity"], "slot_capacity")
    if slot_capacity < 1:
        raise errors.invalid_request("slot_capacity must be at least 1")
    prep_minutes = helpers.require_non_negative_int(body["prep_minutes"], "prep_minutes")

    now = iso_now()
    sid = new_id()
    store = {
        "id": sid,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_seq(),
        "name": name,
        "timezone": tz,
        "slot_capacity": slot_capacity,
        "prep_minutes": prep_minutes,
        "status": "OPEN",
    }
    db.stores[sid] = store
    return success_object(serializers.store_out(store), 201)


@bp.route("/stores/<store_id>", methods=["GET"])
def get_store(store_id):
    principal = authenticate()
    require_roles(principal, ["Member", "StoreOperator", "PlatformAdmin"])
    store = db.stores.get(store_id)
    if store is None:
        raise errors.not_found()
    return success_object(serializers.store_out(store), 200)


@bp.route("/stores/<store_id>/pause", methods=["POST"])
def pause_store(store_id):
    principal = authenticate()
    require_roles(principal, ["StoreOperator", "PlatformAdmin"])
    store = db.stores.get(store_id)
    if store is None:
        raise errors.not_found()
    body = helpers.get_json_body()
    helpers.require_fields(body, ["paused"])
    paused = helpers.require_bool(body["paused"], "paused")
    store["status"] = "PAUSED" if paused else "OPEN"
    from services.mutations import touch
    touch(store)
    return success_object(serializers.store_out(store), 200)


# ---------------- Menu items ----------------
@bp.route("/stores/<store_id>/menu-items", methods=["POST"])
def create_menu_item(store_id):
    principal = authenticate()
    require_roles(principal, ["PlatformAdmin"])
    store = db.stores.get(store_id)
    if store is None:
        raise errors.not_found()
    body = helpers.get_json_body()
    helpers.require_fields(body, ["name", "base_price_cents", "category"])
    name = helpers.require_str(body["name"], "name")
    base_price = helpers.require_non_negative_int(body["base_price_cents"], "base_price_cents")
    category = helpers.require_enum(body["category"], "category", {"BEVERAGE", "FOOD"})
    reward_eligible = True
    if "reward_eligible" in body and body["reward_eligible"] is not None:
        reward_eligible = helpers.require_bool(body["reward_eligible"], "reward_eligible")

    now = iso_now()
    mid = new_id()
    item = {
        "id": mid,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_seq(),
        "store_id": store_id,
        "name": name,
        "base_price_cents": base_price,
        "category": category,
        "reward_eligible": reward_eligible,
        "available": True,
    }
    db.menu_items[mid] = item
    return success_object(serializers.menu_item_out(item), 201)


@bp.route("/stores/<store_id>/menu-items", methods=["GET"])
def list_menu_items(store_id):
    principal = authenticate()
    require_roles(principal, ["Member", "StoreOperator", "PlatformAdmin"])
    store = db.stores.get(store_id)
    if store is None:
        raise errors.not_found()
    limit, offset = helpers.parse_pagination()
    items = [m for m in db.menu_items.values() if m["store_id"] == store_id]
    available = request.args.get("available")
    if available is not None:
        want = available.lower() == "true"
        items = [m for m in items if m["available"] == want]
    items.sort(key=lambda m: (m["created_at"], m["_seq"]))
    total = len(items)
    page = helpers.paginate(items, limit, offset)
    return success_array([serializers.menu_item_out(m) for m in page], limit, offset, total, 200)


@bp.route("/menu-items/<menu_item_id>", methods=["GET"])
def get_menu_item(menu_item_id):
    principal = authenticate()
    require_roles(principal, ["Member", "StoreOperator", "PlatformAdmin"])
    item = db.menu_items.get(menu_item_id)
    if item is None:
        raise errors.not_found()
    return success_object(serializers.menu_item_out(item), 200)


# ---------------- Modifier options ----------------
@bp.route("/menu-items/<menu_item_id>/modifiers", methods=["POST"])
def create_modifier(menu_item_id):
    principal = authenticate()
    require_roles(principal, ["PlatformAdmin"])
    item = db.menu_items.get(menu_item_id)
    if item is None:
        raise errors.not_found()
    body = helpers.get_json_body()
    helpers.require_fields(body, ["group_code", "name", "price_delta_cents"])
    group_code = helpers.require_enum(body["group_code"], "group_code",
                                      {"SIZE", "MILK", "SHOT", "SYRUP"})
    name = helpers.require_str(body["name"], "name")
    price_delta = helpers.require_non_negative_int(body["price_delta_cents"], "price_delta_cents")
    max_quantity = 1
    if "max_quantity" in body and body["max_quantity"] is not None:
        max_quantity = helpers.require_int(body["max_quantity"], "max_quantity")
        if max_quantity < 1:
            raise errors.invalid_request("max_quantity must be at least 1")

    now = iso_now()
    oid = new_id()
    opt = {
        "id": oid,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_seq(),
        "menu_item_id": menu_item_id,
        "group_code": group_code,
        "name": name,
        "price_delta_cents": price_delta,
        "max_quantity": max_quantity,
    }
    db.modifier_options[oid] = opt
    return success_object(serializers.modifier_out(opt), 201)


@bp.route("/menu-items/<menu_item_id>/modifiers", methods=["GET"])
def list_modifiers(menu_item_id):
    principal = authenticate()
    require_roles(principal, ["Member", "StoreOperator", "PlatformAdmin"])
    item = db.menu_items.get(menu_item_id)
    if item is None:
        raise errors.not_found()
    limit, offset = helpers.parse_pagination()
    opts = [o for o in db.modifier_options.values() if o["menu_item_id"] == menu_item_id]
    opts.sort(key=lambda o: (o["created_at"], o["_seq"]))
    total = len(opts)
    page = helpers.paginate(opts, limit, offset)
    return success_array([serializers.modifier_out(o) for o in page], limit, offset, total, 200)


# ---------------- Pickup slots ----------------
@bp.route("/stores/<store_id>/pickup-slots", methods=["POST"])
def create_pickup_slot(store_id):
    principal = authenticate()
    require_roles(principal, ["PlatformAdmin", "StoreOperator"])
    store = db.stores.get(store_id)
    if store is None:
        raise errors.not_found()
    body = helpers.get_json_body()
    helpers.require_fields(body, ["window_start", "window_end"])
    ws = helpers.parse_iso8601(body["window_start"])
    we = helpers.parse_iso8601(body["window_end"])
    if ws is None or we is None:
        raise errors.invalid_request("window_start/window_end must be ISO 8601 instants")
    if not (ws < we):
        raise errors.invalid_request("window_start must be before window_end")

    # Half-open [window_start, window_end) overlap check vs existing slots on the store.
    # Touching at an endpoint is allowed (a.end == b.start). Overlap when
    # new_start < existing_end AND existing_start < new_end.
    for existing in db.pickup_slots.values():
        if existing["store_id"] != store_id:
            continue
        es = helpers.parse_iso8601(existing["window_start"])
        ee = helpers.parse_iso8601(existing["window_end"])
        if ws < ee and es < we:
            raise errors.slot_overlap()

    now = iso_now()
    sid = new_id()
    slot = {
        "id": sid,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_seq(),
        "store_id": store_id,
        "window_start": body["window_start"],
        "window_end": body["window_end"],
    }
    db.pickup_slots[sid] = slot
    return success_object(serializers.pickup_slot_out(slot), 201)


@bp.route("/stores/<store_id>/pickup-slots", methods=["GET"])
def list_pickup_slots(store_id):
    principal = authenticate()
    require_roles(principal, ["Member", "StoreOperator", "PlatformAdmin"])
    store = db.stores.get(store_id)
    if store is None:
        raise errors.not_found()
    limit, offset = helpers.parse_pagination()
    slots = [s for s in db.pickup_slots.values() if s["store_id"] == store_id]
    slots.sort(key=lambda s: (s["created_at"], s["_seq"]))
    total = len(slots)
    page = helpers.paginate(slots, limit, offset)
    return success_array([serializers.pickup_slot_out(s) for s in page], limit, offset, total, 200)


@bp.route("/pickup-slots/<pickup_slot_id>", methods=["GET"])
def get_pickup_slot(pickup_slot_id):
    principal = authenticate()
    require_roles(principal, ["Member", "StoreOperator", "PlatformAdmin"])
    slot = db.pickup_slots.get(pickup_slot_id)
    if slot is None:
        raise errors.not_found()
    return success_object(serializers.pickup_slot_out(slot), 200)


# ---------------- Test clock ----------------
@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    principal = authenticate()
    require_roles(principal, ["PlatformAdmin"])
    body = helpers.get_json_body()
    helpers.require_fields(body, ["to_iso8601"])
    dt = helpers.parse_iso8601(body["to_iso8601"])
    if dt is None:
        raise errors.invalid_request("to_iso8601 must be an ISO 8601 instant")
    clock.set_utc(dt)
    # output: null
    return success_object({}, 200)
