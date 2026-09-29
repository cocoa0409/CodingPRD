"""The logical clock capability (PRD 2.4)."""

from flask import Blueprint

import db
from middleware import auth, body, req_ts
from response import object_response

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    auth("BenefitsAdministrator", "PayrollOperator", "ComplianceAuditor")
    payload = body()
    _raw, parsed = req_ts(payload, "to_iso8601")
    db.db.clock = parsed
    return object_response({"current_utc": db.now_iso()})
