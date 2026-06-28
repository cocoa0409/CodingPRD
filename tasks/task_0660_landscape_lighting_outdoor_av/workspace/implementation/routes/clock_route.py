"""Test-driving logical clock (PRD 2.8, SCAFFOLD §1.5).

POST /_clock/set_current_utc advances the logical clock. Startup default is
2026-04-01T00:00:00Z; before any set call the clock reads exactly this default.
"""

from flask import Blueprint

from clock import clock
from common import get_json_body, parse_iso8601, require_fields, require_string
from errors import err
from middleware import get_auth, require_role
from response import success

bp = Blueprint("clock_route", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    _, role = get_auth()
    require_role(role, {"OperationsAdmin"})
    body = get_json_body()
    require_fields(body, ["to_iso8601"])
    raw = require_string(body, "to_iso8601")
    dt = parse_iso8601(raw)
    if dt is None:
        raise err("ERR_INVALID_REQUEST", "to_iso8601 is not a valid ISO 8601 instant.")
    clock.set(dt)
    return success({}, status=200)
