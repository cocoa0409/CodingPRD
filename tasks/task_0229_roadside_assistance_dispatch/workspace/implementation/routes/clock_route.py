"""Test-driving clock endpoint (PRD §2.10)."""
from flask import Blueprint

import clock
import errors
import validation
from middleware import authenticate, require_roles
from response import object_response

bp = Blueprint("clock_route", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    ident = authenticate()
    require_roles(ident, {"DispatchOperator"})
    body = validation.get_body()
    validation.require_present(body, ["to_iso8601"])
    dt = validation.parse_datetime(body["to_iso8601"], "to_iso8601")
    clock.set_now(dt)
    return object_response({}, 200)
