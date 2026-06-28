"""Technician and technician-shift endpoints (PRD §3.1, §3.2)."""

from flask import Blueprint, request

import errors
from clock import parse_iso8601
from db import db
from helpers import (
    get_body, require_str, parse_pagination, sort_by_created, paginate, stamp_new, touch,
)
from middleware import require_roles
from response import success, list_success
from serializers import serialize_technician, serialize_shift
from services.lookups import (
    get_location_or_404, get_technician_or_404, get_shift_or_404,
    ref_location_or_404,
)

bp = Blueprint("technicians", __name__)


# --- Technicians ----------------------------------------------------------

@bp.post("/locations/<location_id>/technicians")
@require_roles("PlatformAdmin", "LocationManager")
def create_technician(location_id):
    get_location_or_404(location_id)
    body = get_body()
    full_name = require_str(body, "full_name")
    tech = stamp_new({
        "location_id": location_id,
        "full_name": full_name,
        "status": "ACTIVE",
    })
    db.technicians[tech["id"]] = tech
    return success(serialize_technician(tech), 201)


@bp.get("/technicians")
@require_roles("PlatformAdmin", "LocationManager", "Technician")
def list_technicians():
    limit, offset = parse_pagination()
    location_id = request.args.get("location_id")
    status = request.args.get("status")
    items = list(db.technicians.values())
    if location_id is not None:
        items = [t for t in items if t["location_id"] == location_id]
    if status is not None:
        items = [t for t in items if t["status"] == status]
    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return list_success([serialize_technician(t) for t in page], limit, offset, total)


@bp.get("/technicians/<technician_id>")
@require_roles("PlatformAdmin", "LocationManager", "Technician")
def get_technician(technician_id):
    tech = get_technician_or_404(technician_id)
    return success(serialize_technician(tech), 200)


# --- Technician shifts ----------------------------------------------------

def _intervals_overlap(a_start, a_end, b_start, b_end):
    """Half-open [start, end) interiors intersect? Touching endpoints do not."""
    return a_start < b_end and b_start < a_end


@bp.post("/technicians/<technician_id>/shifts")
@require_roles("PlatformAdmin", "LocationManager")
def create_shift(technician_id):
    tech = get_technician_or_404(technician_id)
    body = get_body()
    location_id = require_str(body, "location_id")
    starts_at_raw = require_str(body, "starts_at")
    ends_at_raw = require_str(body, "ends_at")
    try:
        starts_at = parse_iso8601(starts_at_raw)
        ends_at = parse_iso8601(ends_at_raw)
    except ValueError:
        raise errors.invalid_request("starts_at/ends_at must be ISO 8601 instants")
    if ends_at <= starts_at:
        raise errors.invalid_request("ends_at must be after starts_at")
    # Priority 4: body FK existence (location_id).
    ref_location_or_404(location_id)
    # Priority 16: overlap with the same technician's SCHEDULED shifts.
    for s in db.technician_shifts.values():
        if s["technician_id"] != technician_id:
            continue
        if s["status"] != "SCHEDULED":
            continue
        if _intervals_overlap(
            starts_at, ends_at,
            parse_iso8601(s["starts_at"]), parse_iso8601(s["ends_at"]),
        ):
            raise errors.ApiError(
                errors.ERR_SHIFT_OVERLAP, 409,
                "Shift overlaps an existing scheduled shift")
    shift = stamp_new({
        "technician_id": technician_id,
        "location_id": location_id,
        "starts_at": starts_at_raw,
        "ends_at": ends_at_raw,
        "status": "SCHEDULED",
    })
    db.technician_shifts[shift["id"]] = shift
    return success(serialize_shift(shift), 201)


@bp.get("/shifts")
@require_roles("PlatformAdmin", "LocationManager", "Technician")
def list_shifts():
    limit, offset = parse_pagination()
    technician_id = request.args.get("technician_id")
    location_id = request.args.get("location_id")
    status = request.args.get("status")
    items = list(db.technician_shifts.values())
    if technician_id is not None:
        items = [s for s in items if s["technician_id"] == technician_id]
    if location_id is not None:
        items = [s for s in items if s["location_id"] == location_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return list_success([serialize_shift(s) for s in page], limit, offset, total)


@bp.get("/shifts/<shift_id>")
@require_roles("PlatformAdmin", "LocationManager", "Technician")
def get_shift(shift_id):
    shift = get_shift_or_404(shift_id)
    return success(serialize_shift(shift), 200)


@bp.post("/shifts/<shift_id>/cancel")
@require_roles("PlatformAdmin", "LocationManager")
def cancel_shift(shift_id):
    shift = get_shift_or_404(shift_id)
    if shift["status"] != "SCHEDULED":
        raise errors.invalid_state("Shift is not SCHEDULED")
    shift["status"] = "CANCELLED"
    touch(shift)
    return success(serialize_shift(shift), 200)
