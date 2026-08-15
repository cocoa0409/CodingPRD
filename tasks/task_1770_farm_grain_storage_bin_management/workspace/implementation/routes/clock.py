"""Logical clock test-driving endpoint (PRD 2.4). SiteManager only."""
from flask import Blueprint

from clock import CLOCK, parse_iso
from errors import ApiError
from middleware import require_roles
from response import ok
from util import body, required

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    require_roles("SiteManager")
    data = body()
    to_iso8601 = required(data, "to_iso8601")
    if not isinstance(to_iso8601, str):
        raise ApiError("ERR_VALIDATION", 400,
                       "to_iso8601 must be an ISO 8601 timestamp string")
    try:
        parse_iso(to_iso8601)
    except Exception:
        raise ApiError("ERR_VALIDATION", 400,
                       "to_iso8601 must be a valid ISO 8601 timestamp")
    CLOCK.set(to_iso8601)
    return ok({"current_utc": CLOCK.now_iso()})
