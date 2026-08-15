"""LocationBooking endpoints."""

from flask import Blueprint, request
from middleware import require_role, ALL_ROLES
from response import success_object, success_list
from errors import *
from db import store
from services.helpers import (
    require_fields, require_str, parse_date,
    make_entity, touch, get_production, get_location, get_scoped,
    list_filtered, paginate, get_pagination_params,
)
from datetime import timedelta

bp = Blueprint("location_bookings", __name__)


@bp.route("/productions/<pid>/location-bookings", methods=["POST"])
def create_booking(pid):
    user_id, role = require_role("LocationManager")
    p = get_production(pid)
    payload = request.get_json(silent=True) or {}
    require_fields(payload, ["location_id", "booking_start_date", "booking_end_date"])
    loc_id = require_str(payload, "location_id")
    loc = get_location(loc_id)
    start = parse_date(require_str(payload, "booking_start_date"), "booking_start_date")
    end = parse_date(require_str(payload, "booking_end_date"), "booking_end_date")
    buffer_days = loc.get("buffer_days", 0)
    # New booking's buffered closed interval: [start - buffer, end + buffer]
    new_start = start - timedelta(days=buffer_days)
    new_end = end + timedelta(days=buffer_days)
    # Check against all CONFIRMED bookings at same location (closed-closed, touching = conflict)
    for b in store.location_bookings.values():
        if b.get("location_id") == loc_id and b["status"] == "CONFIRMED":
            b_start = parse_date(b["booking_start_date"])
            b_end = parse_date(b["booking_end_date"])
            # Closed interval intersection: [new_start, new_end] vs [b_start, b_end]
            if new_start <= b_end and b_start <= new_end:
                raise ApiError(ERR_BOOKING_BUFFER_CONFLICT,
                               "Booking buffer conflict with existing confirmed booking", 409)
    entity = make_entity({
        "production_id": pid,
        "location_id": loc_id,
        "booking_start_date": payload["booking_start_date"],
        "booking_end_date": payload["booking_end_date"],
        "status": "CONFIRMED",
    })
    store.location_bookings[entity["id"]] = entity
    return success_object(entity, 201)


@bp.route("/productions/<pid>/location-bookings", methods=["GET"])
def list_bookings(pid):
    user_id, role = require_role(*ALL_ROLES)
    p = get_production(pid)
    limit, offset = get_pagination_params(request.args)
    filters = {}
    for f in ("location_id", "status"):
        v = request.args.get(f)
        if v:
            filters[f] = v
    items = list_filtered(store.location_bookings, filters, production_id=pid)
    page, total = paginate(items, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/productions/<pid>/location-bookings/<rid>/release", methods=["POST"])
def release_booking(pid, rid):
    user_id, role = require_role("LocationManager")
    p = get_production(pid)
    b = get_scoped(store.location_bookings, rid, pid, "LocationBooking")
    if b["status"] != "CONFIRMED":
        raise ApiError(ERR_INVALID_STATE, "Booking is not CONFIRMED", 409)
    # No ShootDay for this location in PLANNED/READY/IN_PROGRESS
    loc_id = b["location_id"]
    for sd in store.shoot_days.values():
        if (sd.get("production_id") == pid and sd.get("location_id") == loc_id
                and sd["status"] in ("PLANNED", "READY", "IN_PROGRESS")):
            raise ApiError(ERR_INVALID_STATE,
                           "Cannot release booking while shoot days are live at this location", 409)
    b["status"] = "RELEASED"
    touch(b)
    return success_object(b)
