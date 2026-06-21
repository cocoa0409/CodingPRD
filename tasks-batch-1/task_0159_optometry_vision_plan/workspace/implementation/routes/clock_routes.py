"""Clock test-driving endpoint."""
from flask import Blueprint

import clock
import errors
import helpers
import response
from middleware import require_roles

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
@require_roles("FrontDesk")
def set_clock():
    body = helpers.get_json_body()
    value = helpers.require_str(body, "to_iso8601")
    dt = clock.parse_iso8601(value)
    if dt is None:
        raise errors.invalid_request("to_iso8601 must be a valid ISO 8601 instant")
    clock.set_current_utc(dt)
    return response.object_response({"current_utc": clock.now_iso()}, 200)
