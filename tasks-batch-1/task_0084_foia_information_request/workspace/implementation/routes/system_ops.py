"""Test-driving clock (PRD §3.10)."""

from flask import Blueprint

import clock
from errors import api_error, ERR_INVALID_REQUEST
from helpers import get_json_body, require_str
from middleware import require_roles
from response import ok_object

bp = Blueprint("system_ops", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    require_roles("FoiaOfficer")
    body = get_json_body()
    raw = require_str(body, "to_iso8601")
    dt = clock.parse_iso(raw)
    if dt is None:
        raise api_error(ERR_INVALID_REQUEST, "to_iso8601 must be a valid ISO 8601 instant.")
    clock.set_now(dt)
    return ok_object({}, status=200)
