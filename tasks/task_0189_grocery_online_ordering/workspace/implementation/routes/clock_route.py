"""Test-driving clock endpoint (PRD §3.9, SCAFFOLD §1.5).

POST /_clock/set_current_utc — PlatformAdmin only; sets the server's
deterministic current UTC instant used for staged_at + cold-chain evaluation.
Returns 200 with no resource body.
"""
from flask import Blueprint

import clock
from errors import err, ERR_VALIDATION
from middleware import get_user_context, require_role
import validate as V
from timeutil import parse_iso
from response import object_response

bp = Blueprint("clock_route", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    user_id, role = get_user_context()
    require_role(role, {"PlatformAdmin"})  # PRD §4: PlatformAdmin only
    body = V.get_body()
    to_iso = V.require_str(body, "to_iso8601")
    try:
        dt = parse_iso(to_iso)
    except ValueError:
        err(ERR_VALIDATION, "to_iso8601 must be an ISO 8601 instant")
    clock.set_current_utc(dt)
    # 200 OK with no resource body (PRD §4).
    return object_response({}, 200)
