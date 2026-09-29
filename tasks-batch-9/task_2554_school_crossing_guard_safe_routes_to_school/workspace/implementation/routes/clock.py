"""The logical program clock and its checkpoint sweep (PRD 2.4, 3.9)."""
from flask import Blueprint

import domain
import validate as v
from auth import require
from db import now
from errors import fail
from response import raw_object_response
from timeutil import fmt_dt

bp = Blueprint("clock", __name__)


@bp.post("/srts/_clock/set_current_utc")
def set_current_utc():
    require("ProgramAdmin")
    body = v.body()
    target = v.req_datetime(body, "to_iso8601")

    if target < now():
        fail("ERR_CLOCK_MOVED_BACKWARD",
             "The program clock may never move backwards.")

    activated, ended = domain.advance_clock(target)
    return raw_object_response({
        "current_utc": fmt_dt(now()),
        "activated_assignment_count": activated,
        "ended_assignment_count": ended,
    })
