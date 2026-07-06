"""Test-driving clock endpoints."""
from __future__ import annotations

from flask import Blueprint, request

from clock import CLOCK, iso_format, parse_iso
from errors import InvalidRequest
from middleware import require_roles
from response import success
from services import apply_time_gated_transitions
from validators import as_str


bp = Blueprint("clock_ep", __name__)


@bp.post("/neighborhood/_clock/set_current_utc")
@require_roles("PlatformAdmin")
def set_clock():
    payload = request.get_json(silent=True) or {}
    to = as_str(payload, "to_iso8601")
    try:
        dt = parse_iso(to)
    except ValueError:
        raise InvalidRequest("to_iso8601 must be an ISO 8601 timestamp")
    CLOCK.set(dt)
    applied = apply_time_gated_transitions()
    return success({
        "current_utc": iso_format(CLOCK.now()),
        "applied_transitions": applied,
    })


@bp.get("/neighborhood/_clock/now")
@require_roles("Resident", "Moderator", "BusinessOwner", "AgencyOfficer", "PlatformAdmin")
def get_clock():
    return success({"current_utc": iso_format(CLOCK.now())})
