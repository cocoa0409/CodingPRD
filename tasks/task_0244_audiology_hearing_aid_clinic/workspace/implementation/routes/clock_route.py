"""Test-driving clock endpoint (PRD §3.11)."""

from flask import Blueprint

import validate
import errors
from clock import clock
from timeutil import parse_iso
from middleware import require_auth, require_role, get_json_body
from response import empty_response

bp = Blueprint("clock_route", __name__)


@bp.post("/clinic/_clock/set")
def set_clock():
    auth = require_auth()
    require_role(auth, {"ClinicAdmin"})
    body = get_json_body()
    to_iso8601 = validate.require_str(body, "to_iso8601")
    dt = parse_iso(to_iso8601)
    if dt is None:
        raise errors.invalid_request("to_iso8601 must be a valid ISO 8601 instant.")
    clock.set(dt)
    # Returns 200 OK with no resource body (PRD §4).
    return empty_response(200)
