"""Re-entry plan endpoints (PRD section 3.7)."""

from __future__ import annotations

from datetime import timedelta

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_CASE_NOT_REMOVED,
    ERR_CONDITION_NOT_FOUND,
    ERR_NOT_FOUND,
    ERR_OPEN_REENTRY_PLAN_EXISTS,
    ERR_REENTRY_CONDITIONS_UNMET,
    ERR_REENTRY_NOT_APPROVED,
    ERR_REENTRY_NOT_PROPOSED,
    ERR_SOD_SELF_APPROVAL,
)
from middleware import require_roles
from response import success_object
from services import domain
from util import (
    get_json_body,
    require_non_empty_string_list,
    require_string,
    require_string_allow_empty,
)

bp = Blueprint("reentry", __name__)


def _get_plan_or_404(plan_id: str) -> dict:
    plan = db.reentry_plans.get(plan_id)
    if plan is None:
        raise_err(ERR_NOT_FOUND, "Re-entry plan id does not exist")
    return plan


@bp.route("/re-entry-plans", methods=["POST"])
@require_roles("ThreatAssessor")
def create_reentry_plan(_user_id: str, _role: str):
    body = get_json_body()
    case_id = require_string(body, "case_id")
    conditions = require_non_empty_string_list(body, "conditions")

    case = domain.get_case_or_404(case_id)
    if case["status"] != "REMOVED":
        raise_err(ERR_CASE_NOT_REMOVED,
                  "Re-entry plan creation requires status REMOVED")
    if domain.has_open_reentry_plan(case["id"]):
        raise_err(ERR_OPEN_REENTRY_PLAN_EXISTS,
                  "Case already has a PROPOSED or APPROVED re-entry plan")

    plan = {
        "case_id": case["id"],
        "conditions": [
            {"description": text, "status": "UNMET", "evidence_note": None}
            for text in conditions
        ],
        "status": "PROPOSED",
        "created_by_user_id": _user_id,
        "denial_reason": None,
    }
    db.stamp_new(plan)
    db.reentry_plans[plan["id"]] = plan
    domain.audit(case["id"], "REENTRY_PROPOSED",
                 f"Re-entry plan {plan['id']} proposed with {len(conditions)} conditions",
                 _user_id, _role)
    return success_object(db.public(plan), 201)


@bp.route("/re-entry-plans/<plan_id>/approve", methods=["POST"])
@require_roles("TeamLead")
def approve_reentry_plan(plan_id: str, _user_id: str, _role: str):
    plan = _get_plan_or_404(plan_id)
    if plan["status"] != "PROPOSED":
        raise_err(ERR_REENTRY_NOT_PROPOSED, "Approve requires re-entry plan status PROPOSED")
    case = domain.get_case_or_404(plan["case_id"])
    if case["status"] != "REMOVED":
        raise_err(ERR_CASE_NOT_REMOVED, "Re-entry approval requires case status REMOVED")
    # Segregation of duties: approver may not be the proposing assessor.
    if _user_id == plan["created_by_user_id"]:
        raise_err(ERR_SOD_SELF_APPROVAL,
                  "Approver X-User-ID must differ from the re-entry plan proposer")

    plan["status"] = "APPROVED"
    db.touch(plan)
    domain.audit(plan["case_id"], "REENTRY_APPROVED",
                 f"Re-entry plan {plan_id} approved", _user_id, _role)
    return success_object(db.public(plan))


@bp.route("/re-entry-plans/<plan_id>/deny", methods=["POST"])
@require_roles("TeamLead")
def deny_reentry_plan(plan_id: str, _user_id: str, _role: str):
    body = get_json_body()
    denial_reason = require_string(body, "denial_reason")

    plan = _get_plan_or_404(plan_id)
    if plan["status"] != "PROPOSED":
        raise_err(ERR_REENTRY_NOT_PROPOSED, "Deny requires re-entry plan status PROPOSED")

    plan["status"] = "DENIED"
    plan["denial_reason"] = denial_reason
    db.touch(plan)
    domain.audit(plan["case_id"], "REENTRY_DENIED",
                 f"Re-entry plan {plan_id} denied: {denial_reason}", _user_id, _role)
    return success_object(db.public(plan))


@bp.route("/re-entry-plans/<plan_id>/conditions/<condition_index>/verify", methods=["POST"])
@require_roles("ThreatAssessor")
def verify_reentry_condition(plan_id: str, condition_index: str, _user_id: str, _role: str):
    body = get_json_body()
    evidence_note = require_string_allow_empty(body, "evidence_note")

    plan = _get_plan_or_404(plan_id)
    # conditionIndex resolves at the path tier: not a non-negative integer or
    # out of range -> ERR_CONDITION_NOT_FOUND (404).
    if not condition_index.isdigit():
        raise_err(ERR_CONDITION_NOT_FOUND, "conditionIndex out of range")
    index = int(condition_index)
    if index < 0 or index >= len(plan["conditions"]):
        raise_err(ERR_CONDITION_NOT_FOUND, "conditionIndex out of range")

    if plan["status"] not in ("PROPOSED", "APPROVED"):
        raise_err(ERR_REENTRY_NOT_PROPOSED,
                  "Condition verification requires re-entry plan status PROPOSED or APPROVED")

    plan["conditions"][index]["status"] = "MET"
    plan["conditions"][index]["evidence_note"] = evidence_note
    db.touch(plan)
    return success_object(db.public(plan))


@bp.route("/re-entry-plans/<plan_id>/complete-re-entry", methods=["POST"])
@require_roles("TeamLead")
def complete_reentry(plan_id: str, _user_id: str, _role: str):
    plan = _get_plan_or_404(plan_id)
    if plan["status"] != "APPROVED":
        raise_err(ERR_REENTRY_NOT_APPROVED,
                  "Complete-re-entry requires re-entry plan status APPROVED")
    case = domain.get_case_or_404(plan["case_id"])
    if case["status"] != "REMOVED":
        raise_err(ERR_CASE_NOT_REMOVED, "Complete-re-entry requires case status REMOVED")
    if any(cond["status"] != "MET" for cond in plan["conditions"]):
        raise_err(ERR_REENTRY_CONDITIONS_UNMET,
                  "Complete-re-entry requires every condition to be MET")

    plan["status"] = "REENTERED"
    db.touch(plan)
    domain.audit(case["id"], "REENTRY_COMPLETED",
                 f"Re-entry plan {plan_id} completed", _user_id, _role)

    # The case reopens: PLAN_ACTIVE when an ACTIVE plan exists, else
    # UNDER_ASSESSMENT.
    case["removal_type"] = None
    active_plan = domain.active_plan_for_case(case["id"])
    if active_plan is not None:
        case["status"] = "PLAN_ACTIVE"
    else:
        case["status"] = "UNDER_ASSESSMENT"
    db.touch(case)
    domain.audit(case["id"], "CASE_REOPENED",
                 "Case reopened via re-entry completion", _user_id, _role)

    # Re-entry monitoring check-in only on the PLAN_ACTIVE return branch.
    if case["status"] == "PLAN_ACTIVE":
        due = (db.clock().date() + timedelta(days=domain.REENTRY_CHECKIN_DAYS)).isoformat()
        domain.auto_create_checkin(case["id"], due, respect_day_exclusion=False)

    return success_object(db.public(plan))
