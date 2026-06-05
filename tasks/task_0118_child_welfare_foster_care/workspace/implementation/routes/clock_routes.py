"""System clock route (PRD §1, §3.x). Admin-only logical clock set."""
from flask import Blueprint

import clock
import helpers
import middleware
import response

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set", methods=["POST"])
def set_clock():
    _, role = middleware.authenticate()
    middleware.authorize(role, {"Admin"})
    body = helpers.get_body()
    instant = helpers.require(body, "to_iso8601")
    dt = helpers.parse_dt(instant, "to_iso8601")
    clock.set_clock(dt)
    # No resource returned; data is an empty object.
    return response.success({}, 200)
