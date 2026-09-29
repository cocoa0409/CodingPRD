"""Test-driving logical clock endpoint (PRD §2.12)."""
from flask import Blueprint

import clock
import response
import validate
from errors import ERR_INVALID_REQUEST, fail
from middleware import authorize

bp = Blueprint("clock_routes", __name__)


@bp.post("/_clock/set_current_utc")
@authorize("LoadControlAdmin")
def set_current_utc():
    payload = validate.body()
    raw = validate.req_str(payload, "to_iso8601")
    parsed = clock.parse_iso(raw)
    if parsed is None:
        fail(ERR_INVALID_REQUEST, "Field 'to_iso8601' must be an ISO 8601 instant.")
    clock.set_now(parsed)
    return response.object_response({"current_utc": raw})
