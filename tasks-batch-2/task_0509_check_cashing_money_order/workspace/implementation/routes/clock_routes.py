"""Logical-clock control endpoint (PRD §3.8). StoreManager-only.
Setting the clock does not eagerly recompute any window; window rollover is
evaluated lazily on the next velocity check."""
from flask import Blueprint

import errors
from auth import require_auth, MANAGER_ONLY
from clock import clock, parse_iso
from helpers import get_json_body, require_str
from response import ok

bp = Blueprint("clock_routes", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_auth(MANAGER_ONLY)
    body = get_json_body()
    to_iso8601 = require_str(body, "to_iso8601")
    try:
        dt = parse_iso(to_iso8601)
    except ValueError:
        raise errors.err(errors.ERR_VALIDATION, "to_iso8601 is not a valid ISO 8601 timestamp")
    clock.set(dt)
    return ok({})
