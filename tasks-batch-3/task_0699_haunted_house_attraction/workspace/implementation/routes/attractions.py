"""Attraction endpoints (PRD §3.1, §3.9)."""
from flask import Blueprint, request

import db
import errors
import response
from errors import ApiError
from middleware import get_identity, require_role, get_json_body, parse_pagination
from services import lookup
from services.common import (
    require_str, require_int, require_bool, touch, base_record, sort_and_paginate,
)
from services.serialize import serialize_attraction

bp = Blueprint("attractions", __name__)

READ_ROLES = {"OpsManager", "BoxOffice", "Guest", "Actor"}


@bp.route("/attractions", methods=["POST"])
def create_attraction():
    _, role = get_identity()
    require_role(role, {"OpsManager"})
    body = get_json_body()
    venue_id = require_str(body, "venue_id")
    name = require_str(body, "name")
    min_age = require_int(body, "min_age", minimum=0)
    scare_level = require_int(body, "scare_level", minimum=1, maximum=5)
    throughput_per_slot = require_int(body, "throughput_per_slot", minimum=1)
    requires_waiver = require_bool(body, "requires_waiver", default=True)

    # Existence of body FK after request-shape validation (PRD §2.6).
    lookup.venue(venue_id)

    attraction = base_record()
    attraction.update({
        "venue_id": venue_id,
        "name": name,
        "min_age": min_age,
        "scare_level": scare_level,
        "throughput_per_slot": throughput_per_slot,
        "status": "OPEN",
        "requires_waiver": requires_waiver,
    })
    db.attractions[attraction["id"]] = attraction
    # Creating an OPEN attraction raises the venue's open_attraction_count (a
    # derived count) and recomputes operational_state (derived on read).
    return response.success(serialize_attraction(attraction), 201)


@bp.route("/attractions/<attraction_id>", methods=["GET"])
def get_attraction(attraction_id):
    _, role = get_identity()
    require_role(role, READ_ROLES)
    attraction = lookup.attraction(attraction_id)
    return response.success(serialize_attraction(attraction), 200)


@bp.route("/attractions", methods=["GET"])
def list_attractions():
    _, role = get_identity()
    require_role(role, READ_ROLES)
    limit, offset = parse_pagination()
    venue_id = request.args.get("venue_id")
    records = list(db.attractions.values())
    if venue_id is not None:
        records = [a for a in records if a["venue_id"] == venue_id]
    page, total = sort_and_paginate(records, limit, offset)
    return response.success_list(
        [serialize_attraction(a) for a in page], limit, offset, total, 200
    )


@bp.route("/attractions/<attraction_id>/close_for_season", methods=["POST"])
def close_for_season(attraction_id):
    _, role = get_identity()
    require_role(role, {"OpsManager"})
    attraction = lookup.attraction(attraction_id)
    body = get_json_body()

    # State: must be OPEN or PAUSED (CLOSED is terminal) (PRD §3.9 / scaffold).
    if attraction["status"] not in ("OPEN", "PAUSED"):
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "Attraction is not in a state that can be closed for the season.")

    # OCC on the attraction (PRD §2.10).
    expected = require_int(body, "expected_attraction_version")
    if expected != attraction["version"]:
        raise ApiError(errors.ERR_STALE_ATTRACTION_VERSION, 412,
                       "expected_attraction_version does not match the attraction version.")

    # All TimeSlots of this attraction -> CLOSED.
    for slot in db.time_slots.values():
        if slot["attraction_id"] == attraction_id and slot["status"] != "CLOSED":
            slot["status"] = "CLOSED"
            touch(slot)

    # status -> CLOSED; open_attraction_count and operational_state are derived.
    attraction["status"] = "CLOSED"
    touch(attraction)
    return response.success(serialize_attraction(attraction), 200)
