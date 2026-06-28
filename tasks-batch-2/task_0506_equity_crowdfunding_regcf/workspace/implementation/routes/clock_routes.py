"""Logical-clock test-driving endpoint (PRD 2.9)."""
from flask import Blueprint

from clock import clock, parse_iso
from errors import err
from middleware import get_auth, require_role
from response import success
from validation import require_body, require_str

bp = Blueprint("clock_routes", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    uid, role = get_auth()
    require_role(role, {"ComplianceOfficer"})
    body = require_body()
    raw = require_str(body, "to_iso8601")
    try:
        dt = parse_iso(raw)
    except ValueError:
        raise err("ERR_INVALID_REQUEST", "to_iso8601 must be a valid ISO 8601 instant")
    clock.set(dt)
    return success({})
