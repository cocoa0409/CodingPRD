"""TripSegment flat reads (PRD §3.4).

GET /api/trip-segments/{id}  — PlatformAdmin, Rider
GET /api/trip-segments        — PlatformAdmin, Rider
"""
from flask import Blueprint, request

import errors
from db import db
from middleware import authenticate, require_role, require_rider_owner
from response import success
from util import public, parse_pagination, paginate

bp = Blueprint("trip_segments", __name__)


@bp.get("/api/trip-segments/<segment_id>")
def get_segment(segment_id):
    role, user_id = authenticate()
    require_role(role, {"PlatformAdmin", "Rider"})
    seg = db.trip_segments.get(segment_id)
    if seg is None:
        raise errors.not_found("Trip segment not found")
    # A Rider may only read segments of their own trips (PRD §2.1).
    trip = db.trips.get(seg["trip_id"])
    if trip is not None:
        require_rider_owner(role, user_id, trip["rider_id"])
    return success(public(seg))


@bp.get("/api/trip-segments")
def list_segments():
    role, user_id = authenticate()
    require_role(role, {"PlatformAdmin", "Rider"})
    limit, offset = parse_pagination()

    rows = list(db.trip_segments.values())
    # A Rider sees only segments belonging to their own trips.
    if role == "Rider":
        own_trips = {t["id"] for t in db.trips.values() if t["rider_id"] == user_id}
        rows = [s for s in rows if s["trip_id"] in own_trips]

    trip_id = request.args.get("trip_id")
    if trip_id is not None:
        rows = [s for s in rows if s["trip_id"] == trip_id]
    zone_id = request.args.get("zone_id")
    if zone_id is not None:
        rows = [s for s in rows if s["zone_id"] == zone_id]
    segment_type = request.args.get("segment_type")
    if segment_type is not None:
        rows = [s for s in rows if s["segment_type"] == segment_type]

    page, pagination = paginate(rows, limit, offset)
    return success(page, is_array=True, pagination=pagination)
