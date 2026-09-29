"""The test-driving logical clock control endpoint (PRD 2.5)."""

from flask import Blueprint

import clock
import constants as C
import validate as V
from middleware import authenticate
from response import object_response

bp = Blueprint("clock_control", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    authenticate(C.ROLE_MERCH_OPS_ADMIN)
    body = V.get_body()
    instant = V.req_instant(body, "to_iso8601")
    clock.set_now(instant)
    return object_response({"current_utc": clock.iso(instant)})
