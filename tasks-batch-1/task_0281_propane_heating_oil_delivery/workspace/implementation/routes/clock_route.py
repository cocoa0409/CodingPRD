"""System clock control endpoint (PRD §2.10)."""
from flask import Blueprint

import errors
from clock import parse_iso, set_clock
from common import require_field
from middleware import require_auth, require_role, get_json_body
from response import object_response

bp = Blueprint("clock_route", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    _, role = require_auth()
    require_role(role, {"AccountManager", "Dispatcher"})
    body = get_json_body()
    to_iso = require_field(body, "to_iso8601")
    dt = parse_iso(to_iso) if isinstance(to_iso, str) else None
    if dt is None:
        raise errors.ApiError(errors.ERR_INVALID_REQUEST, 400,
                              "to_iso8601 must be an ISO 8601 datetime")
    set_clock(dt)
    return object_response({}, 200)
