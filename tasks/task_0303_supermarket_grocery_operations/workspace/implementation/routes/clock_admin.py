"""Test-driving logical clock (PRD §3.11)."""
from flask import Blueprint, request

from auth import require_role
from common import require_dict, parse_dt
from clock import clock
from errors import ApiError, ERR_INVALID_REQUEST
from response import success

bp = Blueprint("clock_admin", __name__)


@bp.route("/_clock/advance", methods=["POST"])
def advance_clock():
    require_role("StoreManager")
    body = require_dict(request.get_json(silent=True))
    raw = body.get("to_iso8601")
    if not isinstance(raw, str) or not raw:
        raise ApiError(ERR_INVALID_REQUEST[0], ERR_INVALID_REQUEST[1], "to_iso8601 is required")
    dt = parse_dt(raw, "to_iso8601")
    clock.set(dt)
    current = dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
    return success({"current_utc": current})
