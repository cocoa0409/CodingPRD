"""Ops endpoints: the replenishment sweep and the logical clock."""

import envelope
from auth import auth_and_roles
from calc import replenishment_run
from db import now, set_clock
from flask import Blueprint
from util import body, fmt_clock, v_dt

bp = Blueprint("ops", __name__)


@bp.post("/_replenishment/run")
def run_replenishment():
    auth_and_roles(["DistributionAdmin"])
    result = replenishment_run()
    return envelope.success(result, "object", 200)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    auth_and_roles(["DistributionAdmin"])
    data = body()
    _, parsed = v_dt(data, "to_iso8601")
    set_clock(parsed)
    return envelope.success({"current_utc": fmt_clock(now())}, "object", 200)
