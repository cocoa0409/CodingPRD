"""Test-driving clock endpoint (PRD §2.8)."""
from flask import Blueprint

from clock import set_logical_now, parse_iso8601, logical_now_iso_millis
from errors import ApiError
from helpers import get_json_body, require_str
from middleware import require_auth
from response import success

bp = Blueprint("clock_route", __name__)


@bp.route("/studio/_clock/set_current_utc", methods=["POST"])
@require_auth(["StudioManager"])
def set_clock():
    body = get_json_body()
    to_iso8601 = require_str(body, "to_iso8601")
    dt = parse_iso8601(to_iso8601)
    if dt is None:
        raise ApiError("ERR_INVALID_REQUEST", "to_iso8601 must be an ISO 8601 datetime")
    set_logical_now(dt)
    return success({"current_utc": logical_now_iso_millis()}, 200)
