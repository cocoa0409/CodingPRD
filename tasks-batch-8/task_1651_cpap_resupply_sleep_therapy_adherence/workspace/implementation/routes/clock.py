"""Logical clock and daily ops sweep endpoints (PRD 2.5)."""
from flask import Blueprint

from middleware import authorized, ROLE_OPS_ADMIN
from response import success_object
from services.sweep import run_daily_sweep
from util import CLOCK
from validate import get_body, req_datetime

bp = Blueprint("clock", __name__, url_prefix="/sleep-therapy")


@bp.post("/_clock/set_current_utc")
def set_clock():
    authorized([ROLE_OPS_ADMIN])
    body = get_body()
    to_iso8601 = req_datetime(body, "to_iso8601")
    CLOCK.set(to_iso8601)
    return success_object({"current_utc": CLOCK.now_iso()})


@bp.post("/_ops/run-daily-sweep")
def run_sweep():
    authorized([ROLE_OPS_ADMIN])
    counts = run_daily_sweep()
    return success_object(counts)
