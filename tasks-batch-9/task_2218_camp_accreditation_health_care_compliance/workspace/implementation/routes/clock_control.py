"""The logical-clock control endpoint and its deadline escalations."""

from flask import Blueprint

import clock
import db
import domain
import response
import validators
from middleware import authenticate

bp = Blueprint("clock_control", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    authenticate(
        (
            "AccreditationOfficer",
            "CampDirector",
            "HealthCareStaff",
            "Visitor",
            "StateLicensingAgent",
        )
    )
    data = validators.body()
    moment = validators.req_datetime(data, "to_iso8601")
    clock.set_now(moment)

    today = clock.today().isoformat()
    expired = []
    for deficiency in db.ordered(db.deficiencies):
        if deficiency["status"] not in ("OPEN", "PLAN_ACCEPTED"):
            continue
        visit = db.visits.get(deficiency["visit_id"])
        cycle = db.cycles.get(visit["cycle_id"]) if visit else None
        if cycle is None or cycle["status"] != "IN_CORRECTION":
            continue
        if deficiency["correction_due_date"] is None:
            continue
        if today > deficiency["correction_due_date"]:
            expired.append((deficiency, cycle))

    escalated_cycles = []
    for deficiency, cycle in expired:
        deficiency["status"] = "ESCALATED"
        db.touch(deficiency)
        if cycle["id"] not in [c["id"] for c in escalated_cycles]:
            escalated_cycles.append(cycle)

    for cycle in escalated_cycles:
        cycle["status"] = "TERMINATED"
        db.touch(cycle)
        camp = db.camps.get(cycle["camp_id"])
        if camp is not None:
            camp["accreditation_status"] = "REVOKED"
            db.touch(camp)
            domain.recompute_penalty_balance(camp)
            domain.recompute_posture(camp)
        domain.recompute_open_deficiency_count(cycle)

    return response.ok(
        {
            "current_utc": clock.now_iso(),
            "escalated_deficiency_count": len(expired),
            "terminated_cycle_count": len(escalated_cycles),
        }
    )
