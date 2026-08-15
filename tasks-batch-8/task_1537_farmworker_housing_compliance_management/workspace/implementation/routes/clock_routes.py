"""POST /_clock/set_current_utc"""

from flask import Blueprint

import clock
from errors import err
from middleware import require_roles
from response import success_object
from validate import get_body, req_field

bp = Blueprint("clock_routes", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_roles("OperatorAdmin")
    body = get_body()
    to_iso8601 = req_field(body, "to_iso8601")
    if not isinstance(to_iso8601, str):
        raise err("ERR_INVALID_REQUEST", "to_iso8601 must be an ISO 8601 string")
    try:
        current = clock.set_current(to_iso8601)
    except (ValueError, TypeError):
        raise err("ERR_INVALID_REQUEST", "to_iso8601 is not a valid ISO 8601 timestamp")
    return success_object({"current_utc": current})
