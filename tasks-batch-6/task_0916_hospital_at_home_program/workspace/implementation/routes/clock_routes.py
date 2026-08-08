"""The logical clock endpoint (PRD 2.4)."""

from flask import Blueprint

import clock
import envelope
import ladder
from routes.common import endpoint

bp = Blueprint("clock_routes", __name__)


@endpoint(bp, "/_clock/set_current_utc", ["POST"], ["ProgramAdmin"])
def set_current_utc(caller):
    body = ladder.json_body()
    # rung 4a
    ladder.require_fields(body, ["to_iso8601"])
    # rung 4c
    parsed = ladder.check_datetime(body, "to_iso8601")
    clock.CLOCK.set(body["to_iso8601"], parsed)
    return envelope.RawResult({"current_utc": clock.now_raw()}, 200)
