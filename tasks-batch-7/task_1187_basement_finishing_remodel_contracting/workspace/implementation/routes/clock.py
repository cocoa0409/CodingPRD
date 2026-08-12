"""Test-driving logical clock (PRD §2.5)."""
from flask import Blueprint

from db import set_clock, fmt_ts, clock_now, parse_iso
from errors import fail
from response import ok
from services import expiry_sweep
from validation import auth, require_role, get_body, v_str

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    role, uid = auth()
    require_role(role, "PlatformAdmin")
    body = get_body()
    to_iso8601 = v_str(body, "to_iso8601")
    dt = parse_iso(to_iso8601)
    if dt is None:
        fail("ERR_INVALID_REQUEST", "to_iso8601 must be an ISO 8601 timestamp")
    set_clock(dt)
    # Every clock adjustment triggers the expiry sweep (PRD §2.5).
    expiry_sweep()
    return ok({"current_utc": fmt_ts(clock_now())})
