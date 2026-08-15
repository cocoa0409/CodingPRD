"""Monitoring check-in endpoints (PRD section 3.5)."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_CASE_NOT_PLAN_ACTIVE,
    ERR_CHECKIN_DAY_CONFLICT,
    ERR_CHECKIN_NOT_MISSED,
    ERR_CHECKIN_NOT_SCHEDULED,
    ERR_INVALID_DUE_DATE,
    ERR_NOT_FOUND,
)
from middleware import require_roles
from response import success_object
from services import domain
from util import (
    get_json_body,
    require_date,
    require_enum,
    require_string,
    require_string_allow_empty,
)

bp = Blueprint("checkins", __name__)

OUTCOMES = {"ON_TRACK", "CONCERNS_ESCALATED"}


def _get_checkin_or_404(checkin_id: str) -> dict:
    checkin = db.check_ins.get(checkin_id)
    if checkin is None:
        raise_err(ERR_NOT_FOUND, "Monitoring check-in id does not exist")
    return checkin


@bp.route("/monitoring-check-ins", methods=["POST"])
@require_roles("ThreatAssessor")
def create_checkin(_user_id: str, _role: str):
    body = get_json_body()
    case_id = require_string(body, "case_id")
    due_date = require_date(body, "due_date")

    case = domain.get_case_or_404(case_id)
    if case["status"] != "PLAN_ACTIVE":
        raise_err(ERR_CASE_NOT_PLAN_ACTIVE,
                  "Manual check-in scheduling requires status PLAN_ACTIVE")

    # Temporal rules: not past-dated, then one check-in per case per day.
    from datetime import date as _date
    if _date.fromisoformat(due_date) < db.clock().date():
        raise_err(ERR_INVALID_DUE_DATE, "due_date is before the current logical date")
    if domain.checkin_blocking_exists(case["id"], due_date):
        raise_err(ERR_CHECKIN_DAY_CONFLICT,
                  "A SCHEDULED or MISSED check-in already exists for the case on that day")

    checkin = {
        "case_id": case["id"],
        "due_date": due_date,
        "status": "SCHEDULED",
        "auto_created": False,
        "outcome": None,
        "notes": None,
        "completed_at": None,
    }
    db.stamp_new(checkin)
    db.check_ins[checkin["id"]] = checkin
    return success_object(db.public(checkin), 201)


@bp.route("/monitoring-check-ins/<checkin_id>/complete", methods=["POST"])
@require_roles("ThreatAssessor")
def complete_checkin(checkin_id: str, _user_id: str, _role: str):
    body = get_json_body()
    outcome = require_enum(body, "outcome", OUTCOMES)
    notes = require_string_allow_empty(body, "notes")

    checkin = _get_checkin_or_404(checkin_id)
    if checkin["status"] != "SCHEDULED":
        raise_err(ERR_CHECKIN_NOT_SCHEDULED,
                  "Completion requires check-in status SCHEDULED")

    checkin["status"] = "COMPLETED"
    checkin["outcome"] = outcome
    checkin["notes"] = notes
    checkin["completed_at"] = db.now_logical_iso()
    db.touch(checkin)

    case = domain.get_case_or_404(checkin["case_id"])
    case["consecutive_missed_count"] = 0
    domain.audit(case["id"], "CHECKIN_COMPLETED",
                 f"Monitoring check-in {checkin_id} completed with outcome {outcome}",
                 _user_id, _role)

    # Chain the next check-in per the ACTIVE plan's cadence mode.
    plan = domain.active_plan_for_case(case["id"])
    if plan is not None:
        next_due = domain.next_checkin_due_date(plan, db.clock().date())
        domain.auto_create_checkin(case["id"], next_due, respect_day_exclusion=True)

    if outcome == "CONCERNS_ESCALATED":
        case["escalation_flag"] = True
        domain.audit(case["id"], "ESCALATION_RAISED",
                     "Escalation raised by check-in outcome CONCERNS_ESCALATED",
                     _user_id, _role)

    db.touch(case)  # one case-version increment for the completion
    return success_object(db.public(checkin))


@bp.route("/monitoring-check-ins/<checkin_id>/reschedule", methods=["POST"])
@require_roles("ThreatAssessor")
def reschedule_checkin(checkin_id: str, _user_id: str, _role: str):
    body = get_json_body()
    new_due_date = require_date(body, "new_due_date")

    checkin = _get_checkin_or_404(checkin_id)
    if checkin["status"] != "MISSED":
        raise_err(ERR_CHECKIN_NOT_MISSED, "Reschedule requires check-in status MISSED")

    from datetime import date as _date
    if _date.fromisoformat(new_due_date) < db.clock().date():
        raise_err(ERR_INVALID_DUE_DATE, "new_due_date is before the current logical date")
    if domain.checkin_blocking_exists(checkin["case_id"], new_due_date, exclude_id=checkin["id"]):
        raise_err(ERR_CHECKIN_DAY_CONFLICT,
                  "Another SCHEDULED or MISSED check-in exists for the case on that day")

    checkin["status"] = "SCHEDULED"
    checkin["due_date"] = new_due_date
    # consecutive_missed_count is deliberately NOT reset: miss history preserved.
    db.touch(checkin)
    domain.audit(checkin["case_id"], "CHECKIN_RESCHEDULED",
                 f"Monitoring check-in {checkin_id} rescheduled to {new_due_date}",
                 _user_id, _role)
    return success_object(db.public(checkin))
