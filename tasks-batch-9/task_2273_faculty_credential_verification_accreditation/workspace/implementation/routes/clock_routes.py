"""The logical clock capability (PRD 2.4)."""

from flask import Blueprint

import clock
import middleware
import response
import util
import validate
from constants import READ_ROLES, SYSTEM_ADMIN

bp = Blueprint("clock_routes", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    middleware.require_role(SYSTEM_ADMIN)
    payload = validate.body()
    text = validate.req_str(payload, "current_utc")
    parsed = util.parse_datetime(text)
    if parsed is None:
        validate.bad("Field 'current_utc' must be an ISO 8601 instant.")
    clock.set_clock(text, parsed)
    return response.ok({"current_utc": clock.current_text()})


@bp.route("/_clock", methods=["GET"])
def read_clock():
    middleware.require_role(*READ_ROLES)
    return response.ok({"current_utc": clock.current_text()})
