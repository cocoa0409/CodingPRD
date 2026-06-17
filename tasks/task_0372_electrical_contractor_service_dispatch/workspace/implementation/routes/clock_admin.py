"""Administrative logical-clock endpoint (PRD §2.9).

POST /v1/_clock/set sets the server's current UTC instant to to_iso8601.
"""
from flask import Blueprint

import clock
import response
from errors import err
from helpers import get_json_body, require_fields
from middleware import get_identity, require_roles

bp = Blueprint("clock_admin", __name__)


@bp.post("/v1/_clock/set")
def set_clock():
    _, role = get_identity()
    require_roles(role, {"Dispatcher"})
    body = get_json_body()
    require_fields(body, ["to_iso8601"])
    try:
        dt = clock.parse_iso(body["to_iso8601"])
    except (ValueError, TypeError):
        raise err("ERR_INVALID_REQUEST", "to_iso8601 must be an ISO 8601 datetime")
    clock.set_clock(dt)
    return response.object_response({}, 200)
