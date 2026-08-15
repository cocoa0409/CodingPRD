"""Test-driving logical clock endpoint."""

from flask import Blueprint

import db
from clock import CLOCK, parse_iso
from errors import ApiError
from middleware import require_roles
from response import ok
from services.core import clock_advance
from util import body, required

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    require_roles("ProgramAdmin")
    data = body()
    to_iso8601 = required(data, "to_iso8601")
    if not isinstance(to_iso8601, str):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "to_iso8601 must be an ISO 8601 string")
    try:
        parse_iso(to_iso8601)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "to_iso8601 must be a valid ISO 8601 timestamp")
    CLOCK.set(to_iso8601)
    clock_advance()
    return ok({"current_utc": CLOCK.now_iso()})
