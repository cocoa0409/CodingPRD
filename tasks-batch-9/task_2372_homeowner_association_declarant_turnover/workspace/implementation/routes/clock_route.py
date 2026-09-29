"""Test-driving mount for the logical clock (PRD §2.5)."""
from flask import Blueprint

import auth
import clock
import constants
import response
import util
import validation as v

bp = Blueprint("clock_route", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    auth.require_roles(constants.ROLE_PLATFORM_ADMIN)
    body = v.body()
    _, parsed = v.get_datetime(body, "to_iso8601")
    clock.set_now(parsed)
    return response.object_response({"current_utc": util.fmt_dt(clock.now())})
