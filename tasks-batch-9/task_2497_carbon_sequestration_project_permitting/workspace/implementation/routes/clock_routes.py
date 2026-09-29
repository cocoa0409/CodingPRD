"""Logical clock control endpoint (PRD Section 2.4)."""

from flask import Blueprint

import clock
import middleware as mw
import response

bp = Blueprint("clock_routes", __name__)


@bp.post("/_clock/set_current_utc")
@mw.require("ProgramAdmin")
def set_current_utc():
    payload = mw.body()
    raw = mw.req_ts(payload, "to_iso8601")
    current = clock.set_now(clock.must_parse(raw, "to_iso8601"))
    return response.object_response({"current_utc": clock.fmt(current)})
