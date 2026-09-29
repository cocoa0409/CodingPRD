"""The logical clock endpoint (PRD 2.4)."""
from flask import Blueprint

import clock
import constants as C
import middleware
from response import object_response
from util import fmt_dt

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    middleware.actor([C.ADMIN])
    payload = middleware.body_or_400()
    instant = middleware.req_dt(payload, "to_iso8601")
    clock.set_now(instant)
    return object_response({"current_utc": fmt_dt(clock.now())})
