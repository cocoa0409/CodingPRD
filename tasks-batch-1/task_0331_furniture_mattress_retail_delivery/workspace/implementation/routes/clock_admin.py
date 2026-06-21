"""Test-driving clock endpoint (PRD §3.12)."""
from flask import Blueprint

import clock
import helpers
import response
from errors import err
from middleware import get_auth, require_role

bp = Blueprint("clock_admin", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    _, role = get_auth()
    require_role(role, {"StoreManager"})
    body = helpers.get_body()
    to_iso = helpers.require_str(body, "to_iso8601")
    try:
        parsed = clock.parse_iso(to_iso)
    except (ValueError, TypeError):
        raise err("ERR_INVALID_REQUEST", "to_iso8601 must be an ISO 8601 timestamp.")
    clock.set_now(parsed)
    return response.object_response({}, status=200)
