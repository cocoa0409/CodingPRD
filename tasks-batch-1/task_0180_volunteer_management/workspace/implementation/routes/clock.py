"""Test-only clock control (PRD §2.8)."""
from flask import Blueprint

from db import store
from errors import ApiError
from middleware import require_role
from response import empty_response
from services.common import get_json, require_field
from timeutil import parse_dt

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
@require_role("ComplianceOfficer", "ShiftCoordinator")
def set_clock():
    body = get_json()
    to_iso = require_field(body, "to_iso8601", str)
    try:
        dt = parse_dt(to_iso)
    except (ValueError, TypeError):
        raise ApiError("ERR_INVALID_REQUEST", "to_iso8601 must be ISO-8601")
    with store.lock:
        store.set_clock(dt)
    return empty_response(status=200)
