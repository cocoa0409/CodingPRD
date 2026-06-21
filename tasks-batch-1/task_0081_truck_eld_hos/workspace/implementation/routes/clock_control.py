"""Deterministic clock control (PRD §3.11)."""
from flask import Blueprint

import clock
import errors
import response
import timeutil
import validation as val
from middleware import get_auth, require_role

bp = Blueprint("clock_control", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    _, role = get_auth()
    require_role(role, {"CarrierAdmin"})
    body = val.get_body()
    to_iso = val.require_str(body, "to_iso8601")
    dt = timeutil.parse_iso(to_iso)
    if dt is None:
        raise errors.err(errors.ERR_INVALID_REQUEST, "to_iso8601 is not a valid ISO 8601 instant.")
    clock.set_now(dt)
    return response.object_response({}, 200)
