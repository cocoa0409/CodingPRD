"""Logical clock endpoint (PRD section 2.5): QMSAdmin-only, monotonic forward,
fires the agreement-expiry and revalidation sweeps."""
from flask import Blueprint

from auth import QMS_ADMIN, context, require_role
from domain import run_clock_sweeps
from envelope import success
from errors import err_clock_regression
from store import CLOCK
from timeutil import iso, parse_iso_strict_utc
from validate import get_body

bp = Blueprint("clock", __name__)


@bp.post("/api/_clock/set_current_utc")
def set_current_utc():
    uid, role = context()
    require_role(role, QMS_ADMIN)
    data = get_body()
    target = parse_iso_strict_utc(data.get("to_iso8601"))
    if target is None:
        raise err_clock_regression()
    if target < CLOCK.current:
        raise err_clock_regression()
    CLOCK.current = target
    run_clock_sweeps()
    return success({"current_utc": iso(CLOCK.current)}, 200)
