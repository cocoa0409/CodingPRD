"""SKU, Location, and clock endpoints (PRD §3.1, §3.12)."""
from datetime import datetime, timezone

from flask import Blueprint

from common import (
    new_record, touch, serialize, get_json_body, require_str, require_int,
    require_number, require_enum, optional_enum, paginate, lookup, lookup_fk,
)
from db import store
from errors import err
from middleware import get_identity, require_roles
from response import success, list_success
import calc

bp = Blueprint("catalog", __name__)

ALL_ROLES = ["PlatformAdmin", "ReceivingClerk", "PutawayOperator", "Picker",
             "WavePlanner", "InventoryController"]

# ---------------------------------------------------------------------------
# Sku
# ---------------------------------------------------------------------------
@bp.route("/warehouse/skus", methods=["POST"])
def create_sku():
    _, role = get_identity()
    require_roles(role, ["PlatformAdmin"])
    body = get_json_body()
    sku_code = require_str(body, "sku_code")
    description = require_str(body, "description", allow_empty=True)
    abc_class = require_enum(body, "abc_class", {"A", "B", "C"})
    each_volume = require_number(body, "each_volume_cm3", exclusive_min=0)
    min_qty = require_int(body, "min_qty", minimum=0)
    max_qty = require_int(body, "max_qty")
    if max_qty <= min_qty:
        raise err("ERR_INVALID_REQUEST", "max_qty must be strictly greater than min_qty.")
    # uniqueness (priority 9)
    if any(s["sku_code"] == sku_code for s in store.skus.values()):
        raise err("ERR_DUPLICATE_CODE", "sku_code already exists.")
    rec = new_record()
    rec.update({
        "sku_code": sku_code,
        "description": description,
        "abc_class": abc_class,
        "each_volume_cm3": each_volume,
        "min_qty": min_qty,
        "max_qty": max_qty,
        "on_hand_qty": 0,
        "available_qty": 0,
        "cycle_count_due": True,
    })
    store.skus[rec["id"]] = rec
    return success(serialize(rec), status=201)


@bp.route("/warehouse/skus/<sku_id>", methods=["GET"])
def get_sku(sku_id):
    get_identity()
    rec = lookup(store.skus, sku_id)
    calc.refresh_sku(rec)
    return success(serialize(rec))


@bp.route("/warehouse/skus", methods=["GET"])
def list_skus():
    get_identity()
    from flask import request
    items = list(store.skus.values())
    abc = request.args.get("abc_class")
    if abc:
        items = [s for s in items if s["abc_class"] == abc]
    for s in items:
        calc.refresh_sku(s)
    page, limit, offset, total = paginate(items)
    return list_success(page, limit, offset, total)


# ---------------------------------------------------------------------------
# Location
# ---------------------------------------------------------------------------
ZONES = {"RECEIVING", "RESERVE", "PICK_FACE", "CROSS_DOCK", "STAGING"}


@bp.route("/warehouse/locations", methods=["POST"])
def create_location():
    _, role = get_identity()
    require_roles(role, ["PlatformAdmin", "InventoryController"])
    body = get_json_body()
    location_code = require_str(body, "location_code")
    zone = require_enum(body, "zone", ZONES)
    max_volume = require_number(body, "max_volume_cm3", exclusive_min=0)
    status = optional_enum(body, "status", {"AVAILABLE", "BLOCKED"}, "AVAILABLE")
    pick_face_for_sku_id = body.get("pick_face_for_sku_id")
    if pick_face_for_sku_id is not None:
        # FK existence (priority 3)
        lookup_fk(store.skus, pick_face_for_sku_id, "pick_face_for_sku_id")
    # uniqueness (priority 9)
    if any(l["location_code"] == location_code for l in store.locations.values()):
        raise err("ERR_DUPLICATE_CODE", "location_code already exists.")
    # pick-face dedication: at most one SKU per pick face (priority 11)
    if pick_face_for_sku_id is not None:
        for l in store.locations.values():
            if l.get("pick_face_for_sku_id") == pick_face_for_sku_id:
                raise err("ERR_PICKFACE_TAKEN",
                          "This SKU already has a dedicated pick face.")
    rec = new_record()
    rec.update({
        "location_code": location_code,
        "zone": zone,
        "max_volume_cm3": max_volume,
        "used_volume_cm3": 0,
        "status": status,
        "pick_face_for_sku_id": pick_face_for_sku_id,
    })
    store.locations[rec["id"]] = rec
    return success(serialize(rec), status=201)


@bp.route("/warehouse/locations/<location_id>", methods=["GET"])
def get_location(location_id):
    get_identity()
    rec = lookup(store.locations, location_id)
    calc.refresh_location(rec)
    return success(serialize(rec))


@bp.route("/warehouse/locations", methods=["GET"])
def list_locations():
    get_identity()
    from flask import request
    items = list(store.locations.values())
    zone = request.args.get("zone")
    pick_face = request.args.get("pick_face_for_sku_id")
    status = request.args.get("status")
    if zone:
        items = [l for l in items if l["zone"] == zone]
    if pick_face:
        items = [l for l in items if l.get("pick_face_for_sku_id") == pick_face]
    if status:
        items = [l for l in items if l["status"] == status]
    for l in items:
        calc.refresh_location(l)
    page, limit, offset, total = paginate(items)
    return list_success(page, limit, offset, total)


@bp.route("/warehouse/locations/<location_id>/block", methods=["POST"])
def block_location(location_id):
    _, role = get_identity()
    require_roles(role, ["InventoryController"])
    rec = lookup(store.locations, location_id)
    if rec["status"] != "AVAILABLE":
        raise err("ERR_INVALID_STATE", "Location is not AVAILABLE.")
    rec["status"] = "BLOCKED"
    touch(rec)
    calc.refresh_location(rec)
    return success(serialize(rec))


@bp.route("/warehouse/locations/<location_id>/unblock", methods=["POST"])
def unblock_location(location_id):
    _, role = get_identity()
    require_roles(role, ["InventoryController"])
    rec = lookup(store.locations, location_id)
    if rec["status"] != "BLOCKED":
        raise err("ERR_INVALID_STATE", "Location is not BLOCKED.")
    rec["status"] = "AVAILABLE"
    touch(rec)
    calc.refresh_location(rec)
    return success(serialize(rec))


# ---------------------------------------------------------------------------
# Test clock (PRD §3.12)
# ---------------------------------------------------------------------------
@bp.route("/warehouse/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = get_identity()
    require_roles(role, ["PlatformAdmin"])
    body = get_json_body()
    to_iso = require_str(body, "to_iso8601")
    s = to_iso
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise err("ERR_INVALID_REQUEST", "to_iso8601 must be a valid ISO 8601 instant.")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    store.set_clock(dt)
    return success({})
