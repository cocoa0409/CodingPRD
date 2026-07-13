from flask import Blueprint

from errors import ApiError
from helpers import get_json_body
from middleware import require_role
from response import success_object
from timeutil import set_current_clock, current_clock_iso

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
@require_role("PublicHealthAdmin")
def set_clock():
    body = get_json_body()
    to_iso8601 = body.get("to_iso8601")
    if not isinstance(to_iso8601, str) or not to_iso8601:
        raise ApiError("ERR_VALIDATION", "to_iso8601 is required.", 400)
    try:
        set_current_clock(to_iso8601)
    except ValueError:
        raise ApiError("ERR_VALIDATION", "to_iso8601 must be a valid ISO8601 timestamp.", 400)
    return success_object({"current_utc": current_clock_iso()})
