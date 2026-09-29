"""The test-only logical clock control (PRD 2.4)."""

from flask import Blueprint

import clock
import helpers
import response
from middleware import open_guard
from util import iso_ms

bp = Blueprint("clock_routes", __name__)


@bp.post("/_clock/set_current_utc")
@open_guard
def set_current_utc():
    body = helpers.json_body()
    body.forbid_versions()
    moment = body.timestamp("current_utc", required=True)
    clock.set_now(moment)
    return response.object_response({"current_utc": iso_ms(clock.now())})
