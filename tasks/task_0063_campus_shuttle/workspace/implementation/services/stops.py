"""Stop validation helpers."""
from __future__ import annotations

import re

import db
from errors import err


_CODE_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")


def validate_stop_input(body: dict) -> None:
    code = body.get("code")
    name = body.get("name")
    lat = body.get("latitude")
    lon = body.get("longitude")
    amenities = body.get("amenities", [])
    cap = body.get("capacity_reference")

    if not isinstance(code, str) or not code:
        raise err("ERR_VALIDATION", "code is required")
    if not isinstance(name, str) or not name:
        raise err("ERR_VALIDATION", "name is required")
    try:
        latf = float(lat); lonf = float(lon)
    except (TypeError, ValueError):
        raise err("ERR_VALIDATION", "latitude/longitude must be numbers")
    if not (-90 <= latf <= 90):
        raise err("ERR_VALIDATION", "latitude out of range")
    if not (-180 <= lonf <= 180):
        raise err("ERR_VALIDATION", "longitude out of range")
    if not isinstance(amenities, list):
        raise err("ERR_VALIDATION", "amenities must be a list")
    valid_amenities = {"LIGHTING", "SEATING", "USB", "DISPLAY", "RAMP"}
    for a in amenities:
        if a not in valid_amenities:
            raise err("ERR_VALIDATION", f"invalid amenity: {a}")
    if not isinstance(cap, int) or isinstance(cap, bool):
        raise err("ERR_VALIDATION", "capacity_reference must be integer")
    if not (1 <= cap <= 500):
        raise err("ERR_VALIDATION", "capacity_reference must be in [1,500]")


def code_is_unique_for_active(code: str, exclude_id: str | None = None) -> bool:
    for s in db.stops.values():
        if exclude_id and s["id"] == exclude_id:
            continue
        if s.get("status") == "ACTIVE" and s.get("code") == code:
            return False
    return True


def find_stop_or_ref_not_found(stop_id: str) -> dict:
    s = db.stops.get(stop_id)
    if not s:
        raise err("ERR_REFERENCE_NOT_FOUND", f"Stop {stop_id} not found")
    return s
