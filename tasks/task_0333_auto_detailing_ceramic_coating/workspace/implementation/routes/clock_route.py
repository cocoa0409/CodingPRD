"""Clock test-driving endpoint (PRD §3.9)."""
from flask import Blueprint

import auth
import clock
from errors import err
from response import object_response
from timeutil import parse_iso
from validation import get_body

bp = Blueprint("clock_route", __name__)


@bp.route("/detailing/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    _, role = auth.get_identity()
    auth.require_role(role, {"Scheduler", "ShopManager"})
    body = get_body()
    raw = body.get("to_iso8601")
    dt = parse_iso(raw)
    if dt is None:
        raise err("ERR_INVALID_REQUEST", "to_iso8601 must be an ISO 8601 datetime")
    clock.set_now(dt)
    # Sets the logical clock; changes no business resource. Returns empty object.
    return object_response({})
