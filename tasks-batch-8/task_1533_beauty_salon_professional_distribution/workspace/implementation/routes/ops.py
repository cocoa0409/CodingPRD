"""Ops endpoints: logical clock + daily compliance sweep."""

from flask import Blueprint

import middleware as M
import response as R
import services as S
from db import store, clock_iso

bp = Blueprint("ops", __name__)


@bp.post("/api/_clock/set_current_utc")
def set_clock():
    ctx = M.require_auth()
    data = M.body()
    M.no_unknown(data, {"to_iso8601"})
    to_dt = M.req_datetime(data, "to_iso8601")
    M.require_role(ctx, {"DistributionAdmin"})
    store.clock = to_dt
    return R.success_object({"current_utc": clock_iso()})


@bp.post("/api/ops/run-daily-sweep")
def run_sweep():
    ctx = M.require_auth()
    M.empty_body()
    M.require_role(ctx, {"DistributionAdmin"})
    return R.success_object(S.run_daily_sweep())
