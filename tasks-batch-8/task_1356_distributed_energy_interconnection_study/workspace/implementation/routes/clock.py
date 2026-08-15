"""Test-driving logical clock endpoint (PRD section 2.6)."""
from flask import Blueprint

from clock import CLOCK, parse_iso
from errors import ApiError
from middleware import auth
from response import ok
from util import body

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    auth(["QueueAdministrator"])
    data = body()
    to_iso8601 = data.get("to_iso8601")
    if not isinstance(to_iso8601, str):
        raise ApiError(
            "ERR_INVALID_REQUEST", 400,
            "to_iso8601 is required and must be an ISO 8601 timestamp",
        )
    try:
        parse_iso(to_iso8601)
    except Exception:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400,
            "to_iso8601 must be a valid ISO 8601 timestamp",
        )
    CLOCK.set(to_iso8601)
    # The response echoes the resulting current_utc.
    return ok({"current_utc": CLOCK.raw()}, 200)
