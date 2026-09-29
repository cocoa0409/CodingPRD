"""The logical clock and the deterministic sweep."""

from flask import Blueprint, request

from auth import endpoint
from core import clock_iso, fmt_dt, ok, set_clock
from shapes import body, req_dt
from svc_sweep import run_sweep
from views import ADMIN, ALL_ROLES

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
@endpoint(ADMIN)
def set_current_utc():
    data = body()
    instant = req_dt(data, "current_utc")
    set_clock(instant)
    return ok({"current_utc": clock_iso()})


@bp.get("/_clock")
@endpoint(ALL_ROLES)
def read_clock():
    return ok({"current_utc": clock_iso()})


@bp.post("/ops-runs")
@endpoint(ADMIN)
def ops_run():
    return ok(run_sweep())
