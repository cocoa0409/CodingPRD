"""Van endpoints."""

from flask import Blueprint

from db import store
from serialize import ser_van
from util import (
    caller, require_role, get_body, respond, req_str, req_num, req_enum,
    stamp_new, touch, ApiError,
)
from errors import (
    ERR_NOT_FOUND, ERR_VALIDATION, ERR_INVALID_STATE, ERR_VAN_ROUTE_CONFLICT,
)

bp = Blueprint("vans", __name__)

RECLAIM_SYSTEMS = {"NONE", "BASIC", "ADVANCED"}


@bp.post("/fleet-wash/vans")
def create_van():
    _uid, role = caller()
    require_role(role, {"PlatformAdmin"})
    body = get_body()
    name = req_str(body, "name")
    capacity = req_num(body, "tank_capacity_gal")
    if capacity <= 0:
        raise ApiError(ERR_VALIDATION, "tank_capacity_gal must be > 0")
    reclaim = req_enum(body, "reclaim_system", RECLAIM_SYSTEMS)
    rec = {
        "name": name,
        "tank_capacity_gal": capacity,
        "reclaim_system": reclaim,
        "status": "AVAILABLE",
        "water_loaded_gal": 0,
        "water_reserved_gal": 0,
        "water_used_gal": 0,
    }
    stamp_new(rec)
    store.vans[rec["id"]] = rec
    return respond(ser_van(rec), 201)


@bp.get("/fleet-wash/vans/<vid>")
def get_van(vid):
    _uid, _role = caller()
    rec = store.vans.get(vid)
    if rec is None:
        raise ApiError(ERR_NOT_FOUND, "Van %s not found" % vid)
    return respond(ser_van(rec), 200)


def _route_conflict(van_id, states):
    for r in store.routes.values():
        if r["van_id"] == van_id and r["status"] in states:
            return True
    return False


@bp.post("/fleet-wash/vans/<vid>/events")
def van_event(vid):
    _uid, role = caller()
    require_role(role, {"Dispatcher"})
    rec = store.vans.get(vid)
    if rec is None:
        raise ApiError(ERR_NOT_FOUND, "Van %s not found" % vid)
    body = get_body()
    event = req_str(body, "event_type")
    if event not in ("LOAD_WATER", "MAINTENANCE_START", "MAINTENANCE_END"):
        raise ApiError(ERR_VALIDATION,
                       "event_type must be LOAD_WATER, MAINTENANCE_START, or MAINTENANCE_END")
    if event == "LOAD_WATER":
        gallons = req_num(body, "gallons")
        if gallons <= 0:
            raise ApiError(ERR_VALIDATION, "gallons must be > 0")
        if gallons > rec["tank_capacity_gal"]:
            raise ApiError(ERR_VALIDATION, "gallons must not exceed tank_capacity_gal")
        if rec["status"] != "AVAILABLE":
            raise ApiError(ERR_INVALID_STATE, "Van is not AVAILABLE")
        if _route_conflict(rec["id"], ("PUBLISHED", "LOCKED")):
            raise ApiError(ERR_VAN_ROUTE_CONFLICT,
                           "A route with this van is PUBLISHED or LOCKED")
        rec["water_loaded_gal"] = gallons
        rec["water_reserved_gal"] = 0
        rec["water_used_gal"] = 0
        touch(rec)
    elif event == "MAINTENANCE_START":
        if rec["status"] != "AVAILABLE":
            raise ApiError(ERR_INVALID_STATE, "Van is not AVAILABLE")
        if _route_conflict(rec["id"], ("DRAFT", "PUBLISHED", "LOCKED")):
            raise ApiError(ERR_VAN_ROUTE_CONFLICT,
                           "A non-terminal route exists for this van")
        rec["status"] = "MAINTENANCE"
        touch(rec)
    else:  # MAINTENANCE_END
        if rec["status"] != "MAINTENANCE":
            raise ApiError(ERR_INVALID_STATE, "Van is not in MAINTENANCE")
        rec["status"] = "AVAILABLE"
        touch(rec)
    return respond(ser_van(rec), 200)
