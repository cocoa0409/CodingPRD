"""Test-driving clock endpoint (PRD §3.10)."""
from flask import Blueprint

import clock
from errors import ApiError
from middleware import require_roles
from response import object_response
from services.common import get_body, require_fields
from timeutil import iso_now, parse_iso

bp = Blueprint("clock_route", __name__)


@bp.post("/_clock/set_current_utc")
@require_roles("Officer", "SupervisingJudge", "CompactAdministrator")
def set_current_utc():
    body = get_body()
    require_fields(body, ["to_iso8601"])
    dt = parse_iso(body["to_iso8601"])
    if dt is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, "to_iso8601 must be an ISO 8601 datetime.")
    clock.set_now(dt)
    return object_response({"current_utc": iso_now(clock.now())}, 200)
