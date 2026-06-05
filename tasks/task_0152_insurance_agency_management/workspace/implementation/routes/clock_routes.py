"""Test-driving clock endpoint (PRD §2.11).

Still requires authentication and the AgencyAdmin role; never anonymous.
Returns the SystemClock singleton (current_utc only; no version/updated_at).
"""
from flask import Blueprint

import clock
from middleware import auth, get_json_body
from response import object_response
from util import require_str, parse_dt

bp = Blueprint("clock_routes", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    auth({"AgencyAdmin"})
    body = get_json_body()
    target = parse_dt(require_str(body, "to_iso8601"), "to_iso8601")
    clock.set_current_utc(target)
    return object_response({"current_utc": clock.now_iso_clock()})
