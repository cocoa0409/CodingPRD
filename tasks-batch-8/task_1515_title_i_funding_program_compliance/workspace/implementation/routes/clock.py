"""The test-driving logical clock (PRD 2.10) and its escalation sweep (3.9)."""

from flask import Blueprint

import db
import errors
import middleware
import response
import validators as V

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    _uid, role = middleware.current_user()
    middleware.require_role(role, {"FederalProgramsDirector"})
    data = V.json_body()
    V.check_unknown(data, {"to_iso8601"})
    raw = data.get("to_iso8601")
    if raw is None:
        errors.fail(errors.ERR_INVALID_REQUEST, "Missing required field: to_iso8601.")
    instant = V.parse_instant(raw, "to_iso8601")
    db.set_clock(instant, raw)
    # Escalation sweep: cap_due_date strictly before the new clock date, from
    # OPEN or CAP_RETURNED only, processed in created_at ascending order.
    new_date = instant.date()
    candidates = [
        f for f in db.findings.values()
        if f["status"] in ("OPEN", "CAP_RETURNED")
        and V.parse_date(f["cap_due_date"], "cap_due_date") < new_date
    ]
    candidates.sort(key=lambda f: f["created_at"])
    escalated = []
    for f in candidates:
        f["status"] = "ESCALATED"
        db.touch(f)
        escalated.append(f["id"])
    return response.success_object({
        "current_utc": db.clock_raw(),
        "escalated_finding_ids": escalated,
    })
