"""Venue endpoints (PRD §3.1, §3.9)."""
from flask import Blueprint

import db
import errors
import response
from errors import ApiError
from middleware import get_identity, require_role, get_json_body
from services import lookup
from services.common import require_str, require_int, touch, base_record
from services.serialize import serialize_venue
from services.cascade import pause_attraction_cascade

bp = Blueprint("venues", __name__)

READ_ROLES = {"OpsManager", "BoxOffice", "Guest", "Actor"}


@bp.route("/venues", methods=["POST"])
def create_venue():
    _, role = get_identity()
    require_role(role, {"OpsManager"})
    body = get_json_body()
    name = require_str(body, "name")
    timezone = require_str(body, "timezone")
    venue = base_record()
    venue.update({
        "name": name,
        "timezone": timezone,
        "weather_status": "CLEAR",
    })
    db.venues[venue["id"]] = venue
    return response.success(serialize_venue(venue), 201)


@bp.route("/venues/<venue_id>", methods=["GET"])
def get_venue(venue_id):
    _, role = get_identity()
    require_role(role, READ_ROLES)
    venue = lookup.venue(venue_id)
    return response.success(serialize_venue(venue), 200)


@bp.route("/venues/<venue_id>/weather", methods=["POST"])
def set_weather(venue_id):
    _, role = get_identity()
    require_role(role, {"OpsManager"})
    venue = lookup.venue(venue_id)
    body = get_json_body()
    weather_status = body.get("weather_status")
    if weather_status not in ("CLEAR", "ADVISORY", "SEVERE"):
        raise ApiError(errors.ERR_INVALID_REQUEST, 400,
                       "weather_status must be one of CLEAR, ADVISORY, SEVERE.")

    # Optimistic concurrency on the venue (PRD §2.10).
    expected = require_int(body, "expected_venue_version")
    if expected != venue["version"]:
        raise ApiError(errors.ERR_STALE_VENUE_VERSION, 412,
                       "expected_venue_version does not match the venue version.")

    venue["weather_status"] = weather_status

    if weather_status == "SEVERE":
        # Every OPEN attraction receives an ACTIVE Closure(reason=WEATHER) and
        # runs the pause cascade (PRD §3.9).
        open_attractions = [
            a for a in db.attractions.values()
            if a["venue_id"] == venue_id and a["status"] == "OPEN"
        ]
        for attraction in open_attractions:
            closure = base_record()
            closure.update({
                "attraction_id": attraction["id"],
                "reason": "WEATHER",
                "opened_reservation_refunds": 0,
                "status": "ACTIVE",
            })
            db.closures[closure["id"]] = closure
            pause_attraction_cascade(attraction, closure)

    touch(venue)
    return response.success(serialize_venue(venue), 200)
