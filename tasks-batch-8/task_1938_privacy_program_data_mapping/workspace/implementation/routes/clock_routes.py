from flask import Blueprint

import clock
from middleware import get_body, require_roles
from response import success
from utils import fmt_ts, parse_ts
from errors import ApiError

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    require_roles("PrivacyAdmin")
    body = get_body()
    raw = body.get("to_iso8601")
    try:
        dt = parse_ts(raw)
    except (ValueError, TypeError):
        raise ApiError("ERR_INVALID_REQUEST", "to_iso8601 must be an ISO 8601 timestamp")
    clock.set_current(dt)
    return success({"current_utc": fmt_ts(dt)}, 200)
