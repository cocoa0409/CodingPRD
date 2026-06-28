"""Location endpoints (PRD §3.1)."""

from flask import Blueprint, request

import errors
from db import db
from helpers import (
    get_body, require_str, parse_pagination, sort_by_created, paginate, stamp_new, touch,
)
from middleware import require_roles
from response import success, list_success
from serializers import serialize_location
from services.lookups import get_location_or_404

bp = Blueprint("locations", __name__)


@bp.post("/locations")
@require_roles("PlatformAdmin")
def create_location():
    body = get_body()
    name = require_str(body, "name")
    state_code = require_str(body, "state_code")
    timezone = require_str(body, "timezone")
    loc = stamp_new({
        "name": name,
        "state_code": state_code,
        "timezone": timezone,
        "status": "OPEN",
        "open_booking_count": 0,
    })
    db.locations[loc["id"]] = loc
    return success(serialize_location(loc), 201)


@bp.get("/locations")
@require_roles("PlatformAdmin", "LocationManager", "Member", "Technician")
def list_locations():
    limit, offset = parse_pagination()
    status = request.args.get("status")
    items = list(db.locations.values())
    if status is not None:
        items = [l for l in items if l["status"] == status]
    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return list_success([serialize_location(l) for l in page], limit, offset, total)


@bp.get("/locations/<location_id>")
@require_roles("PlatformAdmin", "LocationManager", "Member", "Technician")
def get_location(location_id):
    loc = get_location_or_404(location_id)
    return success(serialize_location(loc), 200)


@bp.post("/locations/<location_id>/close")
@require_roles("PlatformAdmin", "LocationManager")
def close_location(location_id):
    loc = get_location_or_404(location_id)
    if loc["status"] != "OPEN":
        raise errors.invalid_state("Location is not OPEN")
    loc["status"] = "CLOSED"
    touch(loc)
    return success(serialize_location(loc), 200)


@bp.post("/locations/<location_id>/open")
@require_roles("PlatformAdmin", "LocationManager")
def open_location(location_id):
    loc = get_location_or_404(location_id)
    if loc["status"] != "CLOSED":
        raise errors.invalid_state("Location is not CLOSED")
    loc["status"] = "OPEN"
    touch(loc)
    return success(serialize_location(loc), 200)
