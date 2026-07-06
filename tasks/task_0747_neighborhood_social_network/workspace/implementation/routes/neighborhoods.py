"""Neighborhood endpoints."""
from __future__ import annotations

from flask import Blueprint, request

from db import DB, stamp_new
from errors import InvalidRequest, NotFound
from middleware import require_roles
from paging import apply_pagination
from response import success
from validators import as_str, as_number, as_int, as_enum


bp = Blueprint("neighborhoods", __name__)


STATE_CODES = {"CA", "NY", "TX", "WA", "IL", "MA", "FL", "OR"}
ALL_ROLES = ("Resident", "Moderator", "BusinessOwner", "AgencyOfficer", "PlatformAdmin")


@bp.post("/neighborhood/neighborhoods")
@require_roles("PlatformAdmin")
def create_neighborhood():
    payload = request.get_json(silent=True) or {}
    name = as_str(payload, "name")
    state_code = as_enum(payload, "state_code", STATE_CODES)
    center_lat = as_number(payload, "center_lat")
    center_lng = as_number(payload, "center_lng")
    radius = as_int(payload, "radius_meters")
    if not (-90.0 <= center_lat <= 90.0):
        raise InvalidRequest("center_lat out of range")
    if not (-180.0 <= center_lng <= 180.0):
        raise InvalidRequest("center_lng out of range")
    if not (100 <= radius <= 5000):
        raise InvalidRequest("radius_meters out of range")

    n = {
        "name": name,
        "state_code": state_code,
        "center_lat": center_lat,
        "center_lng": center_lng,
        "radius_meters": radius,
        "safety_posture": "OPEN",
        "unresolved_critical_count": 0,
        "verified_resident_count": 0,
    }
    stamp_new(n)
    DB.neighborhoods[n["id"]] = n
    return success(n, status=201)


@bp.get("/neighborhood/neighborhoods/<nid>")
@require_roles(*ALL_ROLES)
def get_neighborhood(nid: str):
    n = DB.neighborhoods.get(nid)
    if n is None:
        raise NotFound(f"Neighborhood {nid} not found")
    return success(n)


@bp.get("/neighborhood/neighborhoods")
@require_roles(*ALL_ROLES)
def list_neighborhoods():
    state_code = request.args.get("state_code")
    rows = list(DB.neighborhoods.values())
    if state_code is not None:
        rows = [n for n in rows if n["state_code"] == state_code]
    rows.sort(key=lambda n: (n["created_at"], n["id"]))
    page, meta = apply_pagination(rows)
    return success(page, response_type="array", pagination=meta)
