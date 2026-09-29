"""Operator batch checkpoint and the test-driving logical clock."""
from flask import Blueprint

import auth
import calc
import clock
import db
import response
import services
import validate
import web
from errors import fail

bp = Blueprint("ops", __name__)

SHIELDING_STATUSES = ("SUBMITTED", "MANAGER_APPROVED")


def _shielded(assignment):
    for row in services.rows_where("policy_exceptions", assignment_id=assignment["id"]):
        if row["status"] in SHIELDING_STATUSES:
            return True
    return False


def _tier_for(assignment):
    return calc.escalation_tier(calc.days_overdue(assignment["due_date"], clock.now()),
                                assignment["policy_category"])


def _open_case(assignment):
    employee = services.employee_of(assignment)
    row = db.base_row()
    row.update({
        "assignment_id": assignment["id"],
        "employee_id": assignment["employee_id"],
        "notified_manager_id": employee["manager_id"] if employee else None,
        "tier": _tier_for(assignment),
        "status": "OPEN",
        "opened_at": clock.now(),
        "closed_at": None,
        "notice_count": 0,
    })
    db.insert("escalations", row)
    assignment["escalation_state"] = "ESCALATING"
    db.touch(assignment)
    if employee is not None:
        services.adjust_open_escalation(employee, 1)
    return row


def _expire_grants():
    for row in db.sort_created(db.all_rows("policy_exceptions")):
        if row["status"] != "GRANTED":
            continue
        if row["expires_at"] is None or clock.now() < row["expires_at"]:
            continue
        row["status"] = "EXPIRED"
        db.touch(row)
        assignment = db.get("assignments", row["assignment_id"])
        if assignment is None or assignment["ack_state"] != "EXEMPT":
            continue
        assignment["ack_state"] = "PENDING"
        jurisdiction = db.get("jurisdictions", assignment["jurisdiction_id"])
        if jurisdiction is not None:
            assignment["due_date"] = clock.add_days(row["expires_at"],
                                                    jurisdiction["ack_deadline_days"])
        db.touch(assignment)
        employee = services.employee_of(assignment)
        if employee is not None:
            services.adjust_open_ack(employee, 1)
        services.reopen_package(assignment)


@bp.post("/_ops/escalation-sweep")
def escalation_sweep():
    auth.authorize(["HRComplianceAdmin"])
    for assignment in db.sort_created(db.all_rows("assignments")):
        if assignment["ack_state"] != "PENDING":
            continue
        if assignment["escalation_state"] != "NONE":
            continue
        if calc.days_overdue(assignment["due_date"], clock.now()) < 1:
            continue
        if _shielded(assignment):
            continue
        _open_case(assignment)
    for case in db.sort_created(db.all_rows("escalations")):
        if case["status"] not in ("OPEN", "NOTIFIED"):
            continue
        assignment = db.get("assignments", case["assignment_id"])
        if assignment is None:
            continue
        # Re-tiering is a recompute, not a state movement: the scaffold declares no
        # version increment for it, so the case's version is left alone.
        case["tier"] = _tier_for(assignment)
    _expire_grants()
    cases = [case for case in db.sort_created(db.all_rows("escalations"))
             if case["status"] in ("OPEN", "NOTIFIED")]
    return web.paged("escalations", cases)


@bp.post("/_clock/set_current_utc")
def set_clock():
    auth.authorize(["HRComplianceAdmin"])
    data = validate.body()
    target = validate.req_datetime(data, "to_iso8601")
    if target < clock.now():
        fail("ERR_CLOCK_REWIND", "the logical clock is forward-only")
    clock.set_now(target)
    return response.ok(None)
