"""Technician endpoints (PRD §3.7).

POST /api/technicians        — PlatformAdmin
GET  /api/technicians/{id}   — PlatformAdmin, Technician
GET  /api/technicians        — PlatformAdmin, Technician
"""
from flask import Blueprint, request

import errors
from db import db, stamp_new
from middleware import authenticate, require_role
from response import success
from util import (
    get_json_body, require_fields, require_string, require_bool,
    public, parse_pagination, paginate,
)

bp = Blueprint("technicians", __name__)


@bp.post("/api/technicians")
def create_technician():
    role, user_id = authenticate()
    require_role(role, {"PlatformAdmin"})

    body = get_json_body()
    require_fields(body, ["name", "depot_zone_id"])
    require_string(body["name"], "name")
    require_string(body["depot_zone_id"], "depot_zone_id")

    on_shift = body.get("on_shift", True)
    require_bool(on_shift, "on_shift")

    # depot_zone_id references a zone; treat dangling as ERR_REFERENCE_NOT_FOUND.
    if body["depot_zone_id"] not in db.zones:
        raise errors.reference_not_found("depot_zone_id does not reference a zone")

    tech = {
        "name": body["name"],
        "depot_zone_id": body["depot_zone_id"],
        "on_shift": on_shift,
    }
    stamp_new(tech)
    db.technicians[tech["id"]] = tech
    return success(public(tech), status=201)


@bp.get("/api/technicians/<tech_id>")
def get_technician(tech_id):
    role, user_id = authenticate()
    require_role(role, {"PlatformAdmin", "Technician"})
    tech = db.technicians.get(tech_id)
    if tech is None:
        raise errors.not_found("Technician not found")
    return success(public(tech))


@bp.get("/api/technicians")
def list_technicians():
    role, user_id = authenticate()
    require_role(role, {"PlatformAdmin", "Technician"})
    limit, offset = parse_pagination()

    rows = list(db.technicians.values())
    depot_zone_id = request.args.get("depot_zone_id")
    if depot_zone_id is not None:
        rows = [r for r in rows if r["depot_zone_id"] == depot_zone_id]
    on_shift = request.args.get("on_shift")
    if on_shift is not None:
        want = on_shift.lower() in ("true", "1", "yes")
        rows = [r for r in rows if r["on_shift"] == want]

    page, pagination = paginate(rows, limit, offset)
    return success(page, is_array=True, pagination=pagination)
