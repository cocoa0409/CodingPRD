"""The logical clock control (PRD 2.4)."""
from flask import Blueprint

import shape
from common import CLOCK, body, fmt_dt, ok
from authz import endpoint

bp = Blueprint("clock", __name__)

ALL_ROLES = ("QualityManager", "QualityEvaluator", "Agent", "Supervisor",
             "ComplianceAuditor")


@bp.post("/_clock/set_current_utc")
@endpoint(*ALL_ROLES)
def set_current_utc():
    payload = body()
    _raw, moment = shape.want_datetime(payload, "to_iso8601")
    CLOCK.set(moment)
    return ok({"current_utc": fmt_dt(moment)})
