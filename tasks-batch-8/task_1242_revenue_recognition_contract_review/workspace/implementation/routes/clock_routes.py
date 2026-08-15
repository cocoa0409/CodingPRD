from datetime import datetime

from flask import Blueprint

from clock import CLOCK, fmt_ts
from errors import ApiError, ERR_INVALID_REQUEST
from response import ok_object
from validate import require_roles, body

bp = Blueprint("clock_routes", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    require_roles("SystemAdmin")
    data = body()
    raw = data.get("to_iso8601")
    if not isinstance(raw, str) or not raw:
        raise ApiError(ERR_INVALID_REQUEST, 400, "to_iso8601 is required")
    text = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        raise ApiError(ERR_INVALID_REQUEST, 400, "to_iso8601 must be a well-formed ISO 8601 instant")
    CLOCK.set(dt)
    return ok_object({"current_utc": fmt_ts(CLOCK.now())})
