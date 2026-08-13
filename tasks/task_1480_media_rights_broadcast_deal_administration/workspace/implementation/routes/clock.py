from flask import Blueprint

from errors import raise_error
from middleware import require_roles
from response import success_object
from services import clock
from services.system import run_clock_transitions
from util import get_json_body

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    require_roles({"RightsManager"})
    body = get_json_body()
    to_iso8601 = body.get("to_iso8601")
    if not isinstance(to_iso8601, str):
        raise_error("ERR_INVALID_REQUEST", "Field 'to_iso8601' is required and must be an ISO 8601 datetime string")
    dt = clock.parse_iso(to_iso8601)
    if dt is None:
        raise_error("ERR_INVALID_REQUEST", "Field 'to_iso8601' must be a valid ISO 8601 datetime")
    clock.set_current(dt)
    run_clock_transitions()
    return success_object({"current_utc": clock.format_iso(clock.now())})
