"""Administrative logical-clock control (test-driving capability)."""

from flask import Blueprint

import clock
from middleware import endpoint
from response import single
from validation import field, parse_body

bp = Blueprint("clock_admin", __name__)

SET_FIELDS = [field("to_iso8601", "datetime", required=True)]


@bp.post("/_clock/set_current_utc")
@endpoint(["PlatformAdmin"])
def set_current_utc():
    body, _ = parse_body(SET_FIELDS)
    clock.clock.set(clock.parse(body["to_iso8601"]))
    return single({"current_utc": clock.now_iso()})
