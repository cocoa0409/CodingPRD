"""Zone endpoints (PRD §2.5, §3.1).

POST /api/zones        — PlatformAdmin
GET  /api/zones/{id}   — PlatformAdmin, Rider, Technician
GET  /api/zones        — PlatformAdmin, Rider, Technician
"""
from flask import Blueprint, request

import errors
from db import db, stamp_new
from middleware import authenticate, require_role
from response import success
from services.zone import ZONE_TYPES, SLOW
from util import (
    get_json_body, require_fields, require_enum, require_int,
    public, parse_pagination, paginate,
)

bp = Blueprint("zones", __name__)


@bp.post("/api/zones")
def create_zone():
    role, user_id = authenticate()
    require_role(role, {"PlatformAdmin"})

    body = get_json_body()
    require_fields(body, ["name", "zone_type", "priority"])
    if not isinstance(body["name"], str) or body["name"].strip() == "":
        raise errors.invalid_request("name must be a non-empty string")
    require_enum(body["zone_type"], ZONE_TYPES, "zone_type")
    require_int(body["priority"], "priority", minimum=1)

    max_speed = body.get("max_speed_kph")
    if max_speed is not None:
        require_int(max_speed, "max_speed_kph", minimum=0)

    zone = {
        "name": body["name"],
        "zone_type": body["zone_type"],
        "priority": body["priority"],
        "max_speed_kph": max_speed,
    }
    stamp_new(zone)
    db.zones[zone["id"]] = zone
    return success(public(zone), status=201)


@bp.get("/api/zones/<zone_id>")
def get_zone(zone_id):
    role, user_id = authenticate()
    require_role(role, {"PlatformAdmin", "Rider", "Technician"})
    zone = db.zones.get(zone_id)
    if zone is None:
        raise errors.not_found("Zone not found")
    return success(public(zone))


@bp.get("/api/zones")
def list_zones():
    role, user_id = authenticate()
    require_role(role, {"PlatformAdmin", "Rider", "Technician"})
    limit, offset = parse_pagination()

    rows = list(db.zones.values())
    zone_type = request.args.get("zone_type")
    if zone_type is not None:
        rows = [r for r in rows if r["zone_type"] == zone_type]

    page, pagination = paginate(rows, limit, offset)
    return success(page, is_array=True, pagination=pagination)
