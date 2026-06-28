"""Logical clock endpoint (PRD §2.4)."""
from flask import Blueprint

import clock
from common import get_body, require_str
from errors import ApiError
from middleware import auth_context, require_role
from response import object_response

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    _, role = auth_context()
    require_role(role, ["UnderwritingOps"])
    body = get_body()
    raw = require_str(body, "to_iso8601")
    try:
        dt = clock.parse_iso(raw)
    except ValueError:
        raise ApiError("ERR_VALIDATION", "to_iso8601 must be a valid ISO 8601 instant.")
    clock.set_now(dt)
    return object_response({"current_utc": clock.iso_now()}, 200)
