"""Test-driving clock endpoint (PRD 2.5)."""
from flask import Blueprint

import response
from db import db, iso_ms
from errors import ApiError
from middleware import require_user_context, require_role, get_json_body
from services.common import parse_iso

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = require_user_context()
    require_role(role, {"PlatformAdmin"})
    body = get_json_body()
    raw = body.get("to_iso8601")
    if not isinstance(raw, str):
        raise ApiError("ERR_INVALID_REQUEST", "Field 'to_iso8601' is required.")
    dt = parse_iso(raw)
    if dt is None:
        raise ApiError("ERR_INVALID_REQUEST", "Field 'to_iso8601' is not a valid ISO 8601 datetime.")
    with db.lock:
        db.clock.set(dt)
        current = db.clock.now()
    return response.success({"current_utc": iso_ms(current)}, 200)
