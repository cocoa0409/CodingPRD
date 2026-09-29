"""The logical-clock test-driving surface (PRD §2.5)."""

from flask import Blueprint

import store
from auth import authenticate
from errors import fail
from response import empty_response
from services import calc
from validation import Field, parse_iso_instant, validate_body

bp = Blueprint("clock", __name__)


@bp.post("/warranty/_clock/set_current_utc")
def set_current_utc():
    authenticate(("PlatformAdmin",))
    values, _ = validate_body([Field("to_iso8601", "iso")])
    target = parse_iso_instant(values["to_iso8601"])
    if target is None:
        fail("ERR_INVALID_REQUEST", "to_iso8601 must be an ISO 8601 instant.")
    store.set_logical_now(target)
    calc.apply_clock_move()
    return empty_response(200)
