"""Logical-clock control endpoint (PRD §3.11)."""
from flask import Blueprint

import errors
import middleware as mw
from clock import clock
from response import object_response
from timeutil import parse_iso8601

bp = Blueprint("clock_routes", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    auth = mw.authenticate()
    mw.require_role(auth, {"PlatformAdmin"})
    body = mw.get_json_body()
    raw = mw.require_string(body, "to_iso8601")
    try:
        dt = parse_iso8601(raw)
    except ValueError:
        raise errors.err(errors.ERR_INVALID_REQUEST, "Invalid to_iso8601")
    clock.set(dt)
    # No resource returned; data is an empty object (PRD §2.2).
    return object_response({})
