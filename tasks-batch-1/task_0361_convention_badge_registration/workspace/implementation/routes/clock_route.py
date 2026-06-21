"""Test-driving clock endpoint (PRD §3.1, §4)."""
from flask import Blueprint

import clock
import common
import errors
from middleware import authenticate, authorize
import response

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set", methods=["POST"])
def set_clock():
    _, role = authenticate()
    authorize(role, {"ConventionAdmin"})
    body = common.get_body()
    dt = common.require_datetime(body, "to_iso8601")
    clock.set_clock(dt)
    # Output is null per the endpoint table; envelope data is an empty object.
    return response.success({}, 200)
