"""Airport endpoints: create/list/get/suspend/resume + per-airport hangar list."""
from flask import Blueprint

import db
from auth import ALL_ROLES, require_roles
from envelope import success_list, success_obj
from errors import ApiError, ERR_AIRPORT_NOT_ACTIVE, ERR_AIRPORT_NOT_SUSPENDED, ERR_INVALID_REQUEST, ERR_NOT_FOUND
from services.core import ESCALATION_POLICIES, serialize_hangar, touch
from validators import body, paginate, pagination, req_enum, req_int, req_number, req_str
from flask import request

bp = Blueprint("airports", __name__)


def get_airport_or_404(airport_id):
    airport = db.airports.get(airport_id)
    if airport is None:
        raise ApiError(ERR_NOT_FOUND, "Airport not found", 404)
    return airport


@bp.post("/airports")
def create_airport():
    require_roles("AirportManager")
    data = body()
    airport_code = req_str(data, "airport_code")
    name = req_str(data, "name")
    escalation_pct = req_number(data, "escalation_pct")
    if escalation_pct < 0:
        raise ApiError(ERR_INVALID_REQUEST, "escalation_pct must be >= 0", 400)
    escalation_policy = req_enum(data, "escalation_policy", ESCALATION_POLICIES)
    offer_window = req_int(data, "offer_acceptance_window_hours")
    if offer_window <= 0:
        raise ApiError(ERR_INVALID_REQUEST, "offer_acceptance_window_hours must be > 0", 400)
    cure_window = req_int(data, "cure_window_days")
    if cure_window <= 0:
        raise ApiError(ERR_INVALID_REQUEST, "cure_window_days must be > 0", 400)
    grace_days = req_int(data, "late_fee_grace_days")
    if grace_days < 0:
        raise ApiError(ERR_INVALID_REQUEST, "late_fee_grace_days must be >= 0", 400)
    airport = db.new_entity({
        "airport_code": airport_code,
        "name": name,
        "escalation_pct": escalation_pct,
        "escalation_policy": escalation_policy,
        "offer_acceptance_window_hours": offer_window,
        "cure_window_days": cure_window,
        "late_fee_grace_days": grace_days,
        "status": "ACTIVE",
    })
    db.airports[airport["id"]] = airport
    return success_obj(db.public(airport), 201)


@bp.get("/airports")
def list_airports():
    require_roles(*ALL_ROLES)
    limit, offset = pagination()
    page, total = paginate(list(db.airports.values()), limit, offset)
    return success_list([db.public(a) for a in page], limit, offset, total)


@bp.get("/airports/<aid>")
def get_airport(aid):
    require_roles(*ALL_ROLES)
    return success_obj(db.public(get_airport_or_404(aid)), 200)


@bp.post("/airports/<aid>/suspend")
def suspend_airport(aid):
    require_roles("AirportManager")
    airport = get_airport_or_404(aid)
    if airport["status"] != "ACTIVE":
        raise ApiError(ERR_AIRPORT_NOT_ACTIVE, "Airport must be ACTIVE to suspend", 409)
    airport["status"] = "SUSPENDED"
    touch(airport)
    # Cascade compensation: every OPEN offer at this airport -> CANCELLED.
    # QUEUED/OFFERED applications remain in place.
    for offer in db.offers.values():
        if offer["airport_id"] == airport["id"] and offer["status"] == "OPEN":
            offer["status"] = "CANCELLED"
            touch(offer)
    return success_obj(db.public(airport), 200)


@bp.post("/airports/<aid>/resume")
def resume_airport(aid):
    require_roles("AirportManager")
    airport = get_airport_or_404(aid)
    if airport["status"] != "SUSPENDED":
        raise ApiError(ERR_AIRPORT_NOT_SUSPENDED, "Airport must be SUSPENDED to resume", 409)
    airport["status"] = "ACTIVE"
    touch(airport)
    return success_obj(db.public(airport), 200)


@bp.get("/airports/<aid>/hangars")
def list_airport_hangars(aid):
    require_roles(*ALL_ROLES)
    airport = get_airport_or_404(aid)
    size_class = request.args.get("size_class")
    posture = request.args.get("posture")
    items = [h for h in db.hangars.values() if h["airport_id"] == airport["id"]]
    if size_class is not None:
        items = [h for h in items if h["size_class"] == size_class]
    if posture is not None:
        from services.core import hangar_posture
        items = [h for h in items if hangar_posture(h) == posture]
    limit, offset = pagination()
    page, total = paginate(items, limit, offset)
    return success_list([serialize_hangar(h) for h in page], limit, offset, total)
