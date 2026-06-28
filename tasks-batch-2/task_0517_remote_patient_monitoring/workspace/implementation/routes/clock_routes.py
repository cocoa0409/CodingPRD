"""Test-driving logical clock endpoint (PRD §2.12)."""
from flask import Blueprint

import errors
from clock import clock, parse_iso8601
from common import get_json_body
from middleware import require_roles
from response import object_response

bp = Blueprint("clock_routes", __name__)


@bp.post("/_clock/set_current_utc")
@require_roles("BillingSpecialist", "CareCoordinator")
def set_clock():
    body = get_json_body()
    to_iso = body.get("to_iso8601")
    if to_iso is None or to_iso == "":
        raise errors.invalid_request("Missing required field: to_iso8601.")
    dt = parse_iso8601(to_iso)
    if dt is None:
        raise errors.invalid_request("to_iso8601 must be an ISO-8601 instant.")
    clock.set(dt)
    # Output is null per the endpoint table; return an empty data object.
    return object_response({})
