"""Test-driving clock endpoint (PRD §3.14).

POST /_clock/set_current_utc  — LeagueAdmin sets the server's logical UTC clock.
"""
from flask import Blueprint

import clock
from errors import err, ERR_INVALID_REQUEST
from middleware import get_user_context, require_role
from response import object_response
from services import validate
from timeutil import parse_iso

bp = Blueprint("clock_route", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = get_user_context()
    require_role(role, {"LeagueAdmin"})
    data = validate.body()
    to_iso = validate.require_str(data, "to_iso8601")
    try:
        dt = parse_iso(to_iso)
    except ValueError:
        err(ERR_INVALID_REQUEST, "to_iso8601 must be ISO 8601")
    clock.set_current_utc(dt)
    return object_response({})
