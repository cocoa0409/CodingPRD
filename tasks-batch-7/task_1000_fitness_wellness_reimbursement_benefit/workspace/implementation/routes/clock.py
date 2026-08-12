"""Logical clock test-driving endpoint."""
from db import STORE
from errors import err, ERR_INVALID_REQUEST
from middleware import require_roles
from response import success
from services.core import touch
from util import body_json, req, as_str, parse_dt, quarter_key_of
from flask import Blueprint

bp = Blueprint("clock", __name__)


@bp.post("/api/_clock/set_current_utc")
def set_clock():
    require_roles("PlatformAdmin")
    body = body_json()
    raw = as_str(req(body, "to_iso8601"), "to_iso8601")
    new_clock = parse_dt(raw)
    STORE.clock = new_clock
    STORE.clock_raw = raw
    # member eligibility auto-transitions: PENDING -> ELIGIBLE when the clock
    # reaches member.eligibility_date
    for m in STORE.members.values():
        if m["eligibility_status"] == "PENDING" and new_clock >= m["_eligibility_dt"]:
            m["eligibility_status"] = "ELIGIBLE"
            touch(m)
    # enrollment quarter rollover when crossing a calendar-quarter boundary
    qk = quarter_key_of(new_clock)
    for e in STORE.enrollments.values():
        if e["quarter_key"] != qk:
            e["quarter_key"] = qk
            e["quarter_used_cents"] = 0
            touch(e)
    return success({"current_utc": STORE.clock_raw})
