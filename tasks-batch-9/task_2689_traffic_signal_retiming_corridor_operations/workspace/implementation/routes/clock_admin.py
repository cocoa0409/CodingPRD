"""The logical clock's test-driving endpoint (PRD section 2.5)."""

from flask import Blueprint

import auth
import clock
import response
import validators
from auth import SIGNAL_OPS_ADMIN
from errors import fail

bp = Blueprint("clock_admin", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
@auth.roles(SIGNAL_OPS_ADMIN)
def set_current_utc():
    data = validators.body()
    target = validators.req_ts(data, "to_iso8601")
    if target < clock.now():
        fail("ERR_CLOCK_NOT_MONOTONIC")
    clock.set_now(target)
    return response.ok({"current_utc": clock.fmt(clock.now())})
