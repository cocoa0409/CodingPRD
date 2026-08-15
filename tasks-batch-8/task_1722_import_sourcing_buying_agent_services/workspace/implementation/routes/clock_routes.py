"""Test-driving logical clock: POST /sourcing/_clock/set_current_utc."""

from flask import Blueprint

from db import parse_dt, store
from errors import ApiError
from middleware import body_json, require_roles
from response import success_object
from services.domain import run_clock_sweeps

bp = Blueprint("clock", __name__)


@bp.route("/sourcing/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    require_roles("PlatformAdmin")
    data = body_json()
    to_iso8601 = data.get("to_iso8601")
    if not isinstance(to_iso8601, str) or not to_iso8601.strip():
        raise ApiError(
            "ERR_VALIDATION", "Missing required field: to_iso8601", 400
        )
    parsed = parse_dt(to_iso8601)
    if parsed is None:
        raise ApiError(
            "ERR_VALIDATION", "to_iso8601 must be an ISO 8601 datetime", 400
        )
    store.clock = parsed
    store.clock_str = to_iso8601
    run_clock_sweeps()
    return success_object({"current_utc": store.clock_str})
