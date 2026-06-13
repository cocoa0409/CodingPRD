"""Test-driving clock endpoint (PRD §2.11)."""

from flask import Blueprint

import clock
import errors
import response
from middleware import authenticate, require_roles, ROLE_LIBRARIAN, ROLE_MANAGER
from routes import helpers
from timeutil import parse, iso

bp = Blueprint("clock_routes", __name__)


@bp.post("/library/_clock/set")
def set_clock():
    caller = authenticate()
    require_roles(caller, {ROLE_LIBRARIAN, ROLE_MANAGER})
    body = helpers.get_json_body()
    helpers.require_fields(body, ["to_iso8601"])
    try:
        instant = parse(body["to_iso8601"])
    except (ValueError, TypeError):
        raise errors.invalid_request("to_iso8601 must be an ISO 8601 datetime.")
    clock.set_now(instant)
    return response.object_response({"now": iso(clock.now())})
