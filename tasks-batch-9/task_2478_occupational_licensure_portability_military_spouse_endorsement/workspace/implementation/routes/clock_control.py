"""The logical-clock control endpoint (PRD §2.4)."""
from flask import Blueprint

import clock
import response
import validators as v
from constants import ROLE_ADMIN
from middleware import authenticate

bp = Blueprint("clock_control", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    authenticate([ROLE_ADMIN])
    body = v.body()
    to_iso8601 = v.f_datetime(body, "to_iso8601")
    current = clock.set_now(to_iso8601)
    return response.object_response({"current_utc": clock.fmt(current)})
