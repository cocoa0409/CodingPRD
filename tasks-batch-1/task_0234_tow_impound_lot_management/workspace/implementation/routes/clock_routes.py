"""Test-driving clock endpoint (PRD §2.4 / endpoint POST /_clock/set)."""
from flask import Blueprint

from clock import parse_iso, set_clock
from errors import ApiError
from middleware import get_json_body, require_role, require_user_context
from response import object_response
from validators import require_str

bp = Blueprint("clock_routes", __name__)


@bp.route("/_clock/set", methods=["POST"])
def set_server_clock():
    user_id, role = require_user_context()
    require_role(role, {"LotOperator"})
    body = get_json_body()
    to_iso = require_str(body, "to_iso8601")
    dt = parse_iso(to_iso)
    if dt is None:
        raise ApiError("ERR_INVALID_REQUEST", "to_iso8601 must be a valid ISO 8601 instant")
    set_clock(dt)
    return object_response({}, 200)
