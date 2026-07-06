"""POST /_clock/set_current_utc — Manager only."""
from flask import Blueprint, request
from clock import set_now, parse_iso, iso_now
from errors import invalid_request
from middleware import auth_context, require_role, require_json
from response import ok

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    role, _ = auth_context()
    require_role(role, {"Manager"})
    payload = require_json()
    if "to_iso8601" not in payload:
        raise invalid_request("to_iso8601 required")
    dt = parse_iso(payload["to_iso8601"])
    if dt is None:
        raise invalid_request("to_iso8601 must be ISO 8601 UTC")
    set_now(dt)
    return ok({"current_utc": iso_now()})
