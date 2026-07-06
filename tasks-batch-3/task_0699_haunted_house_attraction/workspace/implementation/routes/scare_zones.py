"""ScareZone and ActorShift endpoints (PRD §3.8)."""
from flask import Blueprint, request

import db
import errors
import response
from errors import ApiError
from middleware import get_identity, require_role, get_json_body, parse_pagination
from services import lookup
from services.common import (
    require_str, require_int, require_datetime, touch, base_record, sort_and_paginate,
)
from services.serialize import (
    serialize_scare_zone, serialize_actor_shift, zone_staffing_status,
)
from services.cascade import open_understaffed_closure_and_pause

bp = Blueprint("scare_zones", __name__)

ZONE_READ_ROLES = {"OpsManager", "BoxOffice", "Actor"}
SHIFT_READ_ROLES = {"OpsManager", "Actor"}


# ---------------------------------------------------------------------------
# ScareZone
# ---------------------------------------------------------------------------
@bp.route("/attractions/<attraction_id>/scare-zones", methods=["POST"])
def create_scare_zone(attraction_id):
    _, role = get_identity()
    require_role(role, {"OpsManager"})
    attraction = lookup.attraction(attraction_id)
    body = get_json_body()
    name = require_str(body, "name")
    min_actors = require_int(body, "min_actors", minimum=1)

    zone = base_record()
    zone.update({
        "attraction_id": attraction["id"],
        "name": name,
        "min_actors": min_actors,
        "checked_in_count": 0,
        "staffing_status": "UNDERSTAFFED",
    })
    db.scare_zones[zone["id"]] = zone
    return response.success(serialize_scare_zone(zone), 201)


@bp.route("/scare-zones/<scare_zone_id>", methods=["GET"])
def get_scare_zone(scare_zone_id):
    _, role = get_identity()
    require_role(role, ZONE_READ_ROLES)
    zone = lookup.scare_zone(scare_zone_id)
    return response.success(serialize_scare_zone(zone), 200)


@bp.route("/scare-zones", methods=["GET"])
def list_scare_zones():
    _, role = get_identity()
    require_role(role, ZONE_READ_ROLES)
    limit, offset = parse_pagination()
    attraction_id = request.args.get("attraction_id")
    records = list(db.scare_zones.values())
    if attraction_id is not None:
        records = [z for z in records if z["attraction_id"] == attraction_id]
    page, total = sort_and_paginate(records, limit, offset)
    return response.success_list(
        [serialize_scare_zone(z) for z in page], limit, offset, total, 200
    )


# ---------------------------------------------------------------------------
# ActorShift
# ---------------------------------------------------------------------------
@bp.route("/scare-zones/<scare_zone_id>/actor-shifts", methods=["POST"])
def schedule_shift(scare_zone_id):
    _, role = get_identity()
    require_role(role, {"OpsManager"})
    zone = lookup.scare_zone(scare_zone_id)
    body = get_json_body()
    actor_user_id = require_str(body, "actor_user_id")
    shift_start = require_datetime(body, "shift_start")
    shift_end = require_datetime(body, "shift_end")

    if shift_end <= shift_start:
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, "shift_end must be after shift_start.")

    # Overlap with a mandatory 30-minute rest buffer against every existing
    # non-terminal (SCHEDULED or CHECKED_IN) shift for the same actor_user_id
    # (priority 12, buffered-interval semantics) (PRD §3.8).
    buffer = db.SHIFT_REST_MINUTES
    for existing in db.actor_shifts.values():
        if existing["actor_user_id"] != actor_user_id:
            continue
        if existing["status"] not in ("SCHEDULED", "CHECKED_IN"):
            continue
        e_start = db.parse_iso(existing["shift_start"])
        e_end = db.parse_iso(existing["shift_end"])
        if shift_start < db.add_minutes(e_end, buffer) and e_start < db.add_minutes(shift_end, buffer):
            raise ApiError(errors.ERR_SHIFT_OVERLAP, 409,
                           "New shift violates the rest buffer with an existing shift for this actor.")

    shift = base_record()
    shift.update({
        "scare_zone_id": zone["id"],
        "actor_user_id": actor_user_id,
        "shift_start": db.iso(shift_start),
        "shift_end": db.iso(shift_end),
        "status": "SCHEDULED",
    })
    db.actor_shifts[shift["id"]] = shift
    return response.success(serialize_actor_shift(shift), 201)


@bp.route("/actor-shifts/<shift_id>", methods=["GET"])
def get_shift(shift_id):
    _, role = get_identity()
    require_role(role, SHIFT_READ_ROLES)
    shift = lookup.actor_shift(shift_id)
    return response.success(serialize_actor_shift(shift), 200)


@bp.route("/actor-shifts", methods=["GET"])
def list_shifts():
    _, role = get_identity()
    require_role(role, SHIFT_READ_ROLES)
    limit, offset = parse_pagination()
    scare_zone_id = request.args.get("scare_zone_id")
    records = list(db.actor_shifts.values())
    if scare_zone_id is not None:
        records = [s for s in records if s["scare_zone_id"] == scare_zone_id]
    page, total = sort_and_paginate(records, limit, offset)
    return response.success_list(
        [serialize_actor_shift(s) for s in page], limit, offset, total, 200
    )


@bp.route("/actor-shifts/<shift_id>/check_in", methods=["POST"])
def check_in(shift_id):
    _, role = get_identity()
    require_role(role, {"Actor"})
    shift = lookup.actor_shift(shift_id)

    if shift["status"] != "SCHEDULED":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "Only a SCHEDULED shift can be checked in.")

    # Temporal (priority 11): clock within [shift_start, shift_end).
    start = db.parse_iso(shift["shift_start"])
    end = db.parse_iso(shift["shift_end"])
    now = db.now()
    if not (start <= now < end):
        raise ApiError(errors.ERR_OUTSIDE_SHIFT_WINDOW, 409,
                       "Check-in attempted outside the shift window.")

    shift["status"] = "CHECKED_IN"
    zone = db.scare_zones.get(shift["scare_zone_id"])
    if zone is not None:
        zone["checked_in_count"] += 1
        # staffing_status bubbles up (derived) — touch to bump version/updated_at.
        zone["staffing_status"] = zone_staffing_status(zone)
        touch(zone)
    touch(shift)
    return response.success(serialize_actor_shift(shift), 200)


@bp.route("/actor-shifts/<shift_id>/check_out", methods=["POST"])
def check_out(shift_id):
    _, role = get_identity()
    require_role(role, {"Actor"})
    shift = lookup.actor_shift(shift_id)

    if shift["status"] != "CHECKED_IN":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "Only a CHECKED_IN shift can be checked out.")

    shift["status"] = "CHECKED_OUT"
    zone = db.scare_zones.get(shift["scare_zone_id"])
    dropped_to_understaffed = False
    if zone is not None:
        was_staffed = zone_staffing_status(zone) == "STAFFED"
        zone["checked_in_count"] -= 1
        now_staffing = zone_staffing_status(zone)
        zone["staffing_status"] = now_staffing
        touch(zone)
        if was_staffed and now_staffing == "UNDERSTAFFED":
            dropped_to_understaffed = True

    touch(shift)

    # Cascade: if the zone dropped to UNDERSTAFFED, raise an UNDERSTAFFED closure
    # on the attraction and run the pause cascade (PRD §3.8).
    if dropped_to_understaffed and zone is not None:
        attraction = db.attractions.get(zone["attraction_id"])
        if attraction is not None:
            open_understaffed_closure_and_pause(attraction)

    return response.success(serialize_actor_shift(shift), 200)


@bp.route("/actor-shifts/<shift_id>/cancel", methods=["POST"])
def cancel_shift(shift_id):
    _, role = get_identity()
    require_role(role, {"OpsManager"})
    shift = lookup.actor_shift(shift_id)

    if shift["status"] != "SCHEDULED":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "Only a SCHEDULED shift can be cancelled.")

    shift["status"] = "CANCELLED"
    touch(shift)
    return response.success(serialize_actor_shift(shift), 200)
