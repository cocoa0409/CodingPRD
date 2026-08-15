"""WarehouseZone endpoints: creation, read (derived occupancy), lift-quarantine."""
from flask import Blueprint

import db
from db import new_common, new_id, store, touch
from errors import ApiError
from middleware import ALL_ROLES, get_context, require_roles
from response import created, ok
from services.cascades import lift_quarantine_cascade, zone_view
from validation import parse_body, require_path_entity

bp = Blueprint("zones", __name__)

ZONE_TYPES = ["GLUTEN_FREE", "CONVENTIONAL"]


@bp.post("/warehouse-zones")
def create_zone():
    get_context()
    require_roles(["PlantManager"])
    body = parse_body({
        "zone_name": ("string", True, None),
        "zone_type": ("enum", True, ZONE_TYPES),
        "capacity_pallets": ("integer", True, None),
    }, allow_empty=False)
    if db.dec(body["capacity_pallets"]) <= 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "capacity_pallets must be > 0")
    zone = {
        "id": new_id(),
        "zone_name": body["zone_name"],
        "zone_type": body["zone_type"],
        "capacity_pallets": body["capacity_pallets"],
        "pest_posture": "CLEAR",
        "quarantined_at": None,
    }
    new_common(zone)
    store.warehouse_zones[zone["id"]] = zone
    return created(zone_view(zone))


@bp.get("/warehouse-zones/<zone_id>")
def get_zone(zone_id):
    get_context()
    require_roles(ALL_ROLES)
    zone = require_path_entity(store.warehouse_zones, zone_id, "ERR_ZONE_NOT_FOUND")
    return ok(zone_view(zone))


@bp.post("/warehouse-zones/<zone_id>/lift-quarantine")
def lift_quarantine(zone_id):
    get_context()
    require_roles(["QAManager"])
    zone = require_path_entity(store.warehouse_zones, zone_id, "ERR_ZONE_NOT_FOUND")
    if zone["pest_posture"] != "QUARANTINED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "lift-quarantine requires posture QUARANTINED")
    fresh_none = any(
        i for i in store.pest_inspections.values()
        if i["zone_id"] == zone["id"] and i["status"] == "VERIFIED"
        and i["severity"] == "NONE"
        and i["verified_at"] is not None
        and i["verified_at"] > zone["quarantined_at"])
    if not fresh_none:
        raise ApiError("ERR_QUARANTINE_LIFT_BLOCKED", 409,
                       "No VERIFIED NONE inspection recorded after quarantined_at")
    zone["pest_posture"] = "CLEAR"
    zone["quarantined_at"] = None
    touch(zone)
    lift_quarantine_cascade(zone)
    return ok(zone_view(zone))
