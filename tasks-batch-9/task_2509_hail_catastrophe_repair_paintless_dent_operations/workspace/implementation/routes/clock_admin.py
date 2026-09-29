"""The logical-clock driving endpoint (SCAFFOLD §1.5, outside the business surface)."""

from flask import Blueprint

from clock import clock, parse_instant
from middleware import authenticate
from response import object_response
from validation import json_body, req_instant_string

bp = Blueprint("clock_admin", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    authenticate(("CatastropheDirector",))
    body = json_body()
    to_iso8601 = req_instant_string(body, "to_iso8601")
    clock.set(parse_instant(to_iso8601))
    return object_response({"current_utc": clock.instant()})
