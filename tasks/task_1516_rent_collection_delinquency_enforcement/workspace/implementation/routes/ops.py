"""Ops endpoints (PRD 2.4, 3.6): the SystemOps-only delinquency sweep and the
test-driving logical clock."""

from flask import Blueprint

import db
import middleware
import response
import validators as V
from services import workflows

bp = Blueprint("ops", __name__)


@bp.post("/delinquency-runs")
def run_delinquency_sweep():
    _uid, role = middleware.current_user()
    middleware.require_role(role, middleware.OPS)
    data = V.json_body()
    V.check_unknown(data, set())
    counts = workflows.run_sweep()
    return response.success_object(counts)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    _uid, role = middleware.current_user()
    middleware.require_role(role, middleware.OPS)
    data = V.json_body()
    V.check_unknown(data, {"to_iso8601"})
    raw = V.req_str(data, "to_iso8601")
    instant = V.parse_instant(raw, "to_iso8601")
    db.set_clock(instant, raw)
    return response.success_object({"current_utc": db.clock_raw()})
