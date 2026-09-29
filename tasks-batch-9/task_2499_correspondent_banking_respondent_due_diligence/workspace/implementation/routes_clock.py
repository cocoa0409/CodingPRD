"""The logical-clock test-driving surface (PRD 2.5)."""

from flask import Blueprint

import clock
from common import start
from response import ok
from validate import body, fdate, validate

bp = Blueprint("logical_clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    start(("PlatformAdmin",))
    data = body()
    parsed = validate(data, [fdate("current_utc", True)])
    clock.set_now(parsed["current_utc"])
    return ok({"current_utc": clock.iso(clock.now())})
