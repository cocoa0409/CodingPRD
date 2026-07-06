"""Closure endpoints (PRD §3.9)."""
from flask import Blueprint, request

import db
import errors
import response
from errors import ApiError
from middleware import get_identity, require_role, get_json_body, parse_pagination
from services import lookup
from services.common import require_int, require_enum, touch, base_record, sort_and_paginate
from services.serialize import serialize_closure
from services.cascade import pause_attraction_cascade

bp = Blueprint("closures", __name__)

READ_ROLES = {"OpsManager", "BoxOffice"}


@bp.route("/attractions/<attraction_id>/closures", methods=["POST"])
def open_closure(attraction_id):
    _, role = get_identity()
    require_role(role, {"OpsManager"})
    attraction = lookup.attraction(attraction_id)
    body = get_json_body()
    reason = require_enum(body, "reason", {"WEATHER", "SAFETY", "UNDERSTAFFED"})

    # State (priority 5): a closure may be opened only on an OPEN attraction
    # (Attraction OPEN->PAUSED).
    if attraction["status"] != "OPEN":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "A closure can only be opened on an OPEN attraction.")

    # OCC (PRD §2.10).
    expected = require_int(body, "expected_attraction_version")
    if expected != attraction["version"]:
        raise ApiError(errors.ERR_STALE_ATTRACTION_VERSION, 412,
                       "expected_attraction_version does not match the attraction version.")

    closure = base_record()
    closure.update({
        "attraction_id": attraction["id"],
        "reason": reason,
        "opened_reservation_refunds": 0,
        "status": "ACTIVE",
    })
    db.closures[closure["id"]] = closure

    # Opening drives OPEN->PAUSED and runs the three-layer pause cascade.
    pause_attraction_cascade(attraction, closure)
    return response.success(serialize_closure(closure), 201)


@bp.route("/closures/<closure_id>", methods=["GET"])
def get_closure(closure_id):
    _, role = get_identity()
    require_role(role, READ_ROLES)
    closure = lookup.closure(closure_id)
    return response.success(serialize_closure(closure), 200)


@bp.route("/closures", methods=["GET"])
def list_closures():
    _, role = get_identity()
    require_role(role, READ_ROLES)
    limit, offset = parse_pagination()
    attraction_id = request.args.get("attraction_id")
    records = list(db.closures.values())
    if attraction_id is not None:
        records = [c for c in records if c["attraction_id"] == attraction_id]
    page, total = sort_and_paginate(records, limit, offset)
    return response.success_list(
        [serialize_closure(c) for c in page], limit, offset, total, 200
    )


@bp.route("/closures/<closure_id>/lift", methods=["POST"])
def lift_closure(closure_id):
    _, role = get_identity()
    require_role(role, {"OpsManager"})
    closure = lookup.closure(closure_id)
    body = get_json_body()
    attraction = db.attractions.get(closure["attraction_id"])
    if attraction is None:
        raise ApiError(errors.ERR_NOT_FOUND, 404, "Referenced attraction does not exist.")

    # State (priority 5): closure must be ACTIVE.
    if closure["status"] != "ACTIVE":
        raise ApiError(errors.ERR_INVALID_STATE, 409, "Only an ACTIVE closure can be lifted.")

    # Lifting requires the venue's weather_status is not SEVERE (state precondition).
    venue = db.venues.get(attraction["venue_id"])
    if venue is not None and venue["weather_status"] == "SEVERE":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "A closure cannot be lifted while weather is SEVERE.")

    # OCC on the attraction (PRD §2.10).
    expected = require_int(body, "expected_attraction_version")
    if expected != attraction["version"]:
        raise ApiError(errors.ERR_STALE_ATTRACTION_VERSION, 412,
                       "expected_attraction_version does not match the attraction version.")

    # Closure -> LIFTED.
    closure["status"] = "LIFTED"
    touch(closure)

    # If no other ACTIVE closure remains, return the attraction PAUSED->OPEN and
    # restore future SCHEDULED slots.
    other_active = any(
        c["attraction_id"] == attraction["id"] and c["status"] == "ACTIVE"
        for c in db.closures.values()
    )
    if not other_active and attraction["status"] == "PAUSED":
        attraction["status"] = "OPEN"
        now = db.now()
        for slot in db.time_slots.values():
            if slot["attraction_id"] != attraction["id"]:
                continue
            if slot["status"] != "CLOSED":
                continue
            window_start = db.parse_iso(slot["window_start"])
            if window_start is not None and window_start >= now:
                slot["status"] = "SCHEDULED"
                touch(slot)
        touch(attraction)

    return response.success(serialize_closure(closure), 200)
