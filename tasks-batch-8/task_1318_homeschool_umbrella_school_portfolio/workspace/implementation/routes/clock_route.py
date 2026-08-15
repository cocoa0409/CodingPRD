"""Logical clock test-driving endpoint."""
from flask import Blueprint

import clock
from middleware import route
from response import success_object
from validation import get_body, req_datetime

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
@route(["AcademicDirector"])
def set_current_utc():
    body = get_body()
    to_iso8601 = req_datetime(body, "to_iso8601")
    current = clock.CLOCK.set(to_iso8601)
    return success_object({"current_utc": clock.fmt(current)})
