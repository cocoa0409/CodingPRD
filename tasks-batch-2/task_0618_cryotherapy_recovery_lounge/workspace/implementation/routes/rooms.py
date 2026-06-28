"""Room endpoints (PRD §3.1)."""

from flask import Blueprint, request

import errors
from db import db
from helpers import (
    get_body, require_str, parse_pagination, sort_by_created, paginate, stamp_new,
)
from middleware import require_roles
from response import success, list_success
from serializers import serialize_room
from services.lookups import (
    get_location_or_404, get_room_or_404, ref_service_type_or_404,
)

bp = Blueprint("rooms", __name__)


@bp.post("/locations/<location_id>/rooms")
@require_roles("PlatformAdmin", "LocationManager")
def create_room(location_id):
    # Priority 3: path existence.
    loc = get_location_or_404(location_id)
    body = get_body()
    service_type_id = require_str(body, "service_type_id")
    name = require_str(body, "name")
    # Priority 4: body FK existence (before location-closed check, priority 10).
    ref_service_type_or_404(service_type_id)
    # Priority 10: location must be OPEN to create a room.
    if loc["status"] != "OPEN":
        raise errors.ApiError(errors.ERR_LOCATION_CLOSED, 409, "Location is CLOSED")
    room = stamp_new({
        "location_id": location_id,
        "service_type_id": service_type_id,
        "name": name,
        "status": "AVAILABLE",
    })
    db.rooms[room["id"]] = room
    return success(serialize_room(room), 201)


@bp.get("/rooms")
@require_roles("PlatformAdmin", "LocationManager", "Member", "Technician")
def list_rooms():
    limit, offset = parse_pagination()
    location_id = request.args.get("location_id")
    service_type_id = request.args.get("service_type_id")
    status = request.args.get("status")
    items = list(db.rooms.values())
    if location_id is not None:
        items = [r for r in items if r["location_id"] == location_id]
    if service_type_id is not None:
        items = [r for r in items if r["service_type_id"] == service_type_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return list_success([serialize_room(r) for r in page], limit, offset, total)


@bp.get("/rooms/<room_id>")
@require_roles("PlatformAdmin", "LocationManager", "Member", "Technician")
def get_room(room_id):
    room = get_room_or_404(room_id)
    return success(serialize_room(room), 200)
