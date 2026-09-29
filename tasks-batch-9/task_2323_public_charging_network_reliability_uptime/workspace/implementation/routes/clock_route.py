"""The logical-clock test-driving endpoint (PRD §2.4)."""
from flask import Blueprint

import clock
import validation
from middleware import endpoint
from response import object_response

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
@endpoint()
def set_current_utc():
    body = validation.json_body()
    instant = validation.as_datetime(body, "current_utc", required=True)
    clock.set_now(instant)
    return object_response({"current_utc": clock.iso(clock.now())})
