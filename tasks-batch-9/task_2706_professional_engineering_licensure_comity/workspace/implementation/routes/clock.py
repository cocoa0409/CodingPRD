"""The logical board clock (PRD 2.5)."""
from flask import Blueprint

import cascade
import db
from errors import ApiError
from middleware import endpoint
from response import ok
from util import fmt_iso
from validate import body, check_dt

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
@endpoint("BoardSecretary")
def set_clock():
    data = body()
    if "to_iso8601" in data and data["to_iso8601"] is not None:
        target = check_dt("to_iso8601", data["to_iso8601"])
    elif "current_utc" in data and data["current_utc"] is not None:
        target = check_dt("current_utc", data["current_utc"])
    else:
        raise ApiError("ERR_INVALID_REQUEST", "to_iso8601 is required")
    if target < db.clock():
        raise ApiError("ERR_CLOCK_REWIND_FORBIDDEN",
                       "the logical clock may not move backwards")
    summary = cascade.advance_clock(target)
    payload = {"current_utc": fmt_iso(db.clock())}
    payload.update(summary)
    return ok(payload)
