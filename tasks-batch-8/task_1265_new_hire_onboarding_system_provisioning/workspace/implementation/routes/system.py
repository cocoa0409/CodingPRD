"""Test-driving logical clock endpoint (PRD §2.5)."""

from flask import Blueprint

from auth import require_roles
from db import clock
from sweep import sweep
from util import success, get_body, req_present, as_dt, fmt_dt

bp = Blueprint("system", __name__)


@bp.post("/api/_clock/set_current_utc")
def set_clock():
    require_roles("HRAdmin")
    body = get_body()
    dt = as_dt(req_present(body, "to_iso8601"), "to_iso8601")
    clock.current = dt
    # Advancing the clock evaluates every pending time-based transition as
    # one atomic sweep.
    sweep()
    return success({"current_utc": fmt_dt(clock.current)})
