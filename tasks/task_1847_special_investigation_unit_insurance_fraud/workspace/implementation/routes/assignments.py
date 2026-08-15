"""Assignment endpoints (PRD §3.3): concurrency-guarded assignment, termination."""

from __future__ import annotations

from flask import Blueprint

import db
from constants import CASE_TERMINAL
from errors import (
    raise_err,
    ERR_INVALID_STATE,
    ERR_CASE_NOT_IN_REQUIRED_STATE,
    ERR_INVESTIGATOR_INELIGIBLE,
    ERR_STALE_VERSION,
)
from middleware import require_roles
from response import success_list, success_object
from serializers import pub_assignment
from services.cascade import active_assignment_for_case, adjust_case_count
from util import (
    apply_filters,
    fk_or_404,
    get_json_body,
    page_of,
    parse_pagination,
    path_or_404,
    require_string,
    require_version,
    sort_created,
)

bp = Blueprint("assignments", __name__)


@bp.post("/siu/cases/<caseId>/assignments")
@require_roles("SIUManager")
def create_assignment(caseId: str, _user_id: str, _role: str):
    body = get_json_body()
    investigator_id = require_string(body, "investigator_id")
    expected_case_version = require_version(body, "expected_case_version")
    case = path_or_404(db.cases, caseId, "SIUCase")
    investigator = fk_or_404(db.investigators, investigator_id, "Investigator")
    # Rung 5: assignment creation is valid only while OPEN or UNDER_INVESTIGATION.
    if case.get("status") not in ("OPEN", "UNDER_INVESTIGATION"):
        raise_err(ERR_INVALID_STATE, "Case must be OPEN or UNDER_INVESTIGATION for assignment")
    # Rung 7: investigator eligibility (status, certification, capacity).
    claim = db.claims.get(case.get("claim_id")) or {}
    if (
        investigator.get("status") != "ACTIVE"
        or claim.get("state_code") not in (investigator.get("state_certifications") or [])
        or int(investigator.get("active_case_count", 0)) >= int(investigator.get("max_active_cases", 0))
    ):
        raise_err(ERR_INVESTIGATOR_INELIGIBLE, "Investigator fails status/certification/capacity check")
    # Rung 8: optimistic concurrency on the case.
    if expected_case_version != int(case.get("version", 0)):
        raise_err(ERR_STALE_VERSION, "expected_case_version does not match the case version")

    # Atomic handoff: an existing ACTIVE assignment flips to REASSIGNED.
    previous = active_assignment_for_case(case["id"])
    if previous is not None:
        previous["status"] = "REASSIGNED"
        db.touch(previous)
        adjust_case_count(previous.get("investigator_id"), -1)

    assignment = {
        "case_id": case["id"],
        "investigator_id": investigator["id"],
        "assigned_by_user_id": _user_id,
        "status": "ACTIVE",
        "assigned_at": db.clock.now_string(),
        "completed_at": None,
    }
    db.stamp_new(assignment)
    db.assignments[assignment["id"]] = assignment
    adjust_case_count(investigator["id"], +1)

    case["assigned_investigator_id"] = investigator["id"]
    if case.get("status") == "OPEN":
        case["status"] = "UNDER_INVESTIGATION"
    db.touch(case)
    return success_object(pub_assignment(assignment), 201)


@bp.get("/siu/assignments/<assignmentId>")
@require_roles("SIUManager", "SIUInvestigator", "SIUComplianceOfficer")
def get_assignment(assignmentId: str, _user_id: str, _role: str):
    assignment = path_or_404(db.assignments, assignmentId, "Assignment")
    return success_object(pub_assignment(assignment))


@bp.get("/siu/cases/<caseId>/assignments")
@require_roles("SIUManager", "SIUInvestigator", "SIUComplianceOfficer")
def list_case_assignments(caseId: str, _user_id: str, _role: str):
    case = path_or_404(db.cases, caseId, "SIUCase")
    limit, offset = parse_pagination()
    items = sort_created([a for a in db.assignments.values() if a.get("case_id") == case["id"]])
    page, total = page_of(items, limit, offset)
    return success_list([pub_assignment(a) for a in page], limit, offset, total)


@bp.get("/siu/assignments")
@require_roles("SIUManager", "SIUInvestigator", "SIUComplianceOfficer")
def list_assignments(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = apply_filters(list(db.assignments.values()), ["case_id", "investigator_id", "status"])
    items = sort_created(items)
    page, total = page_of(items, limit, offset)
    return success_list([pub_assignment(a) for a in page], limit, offset, total)


@bp.post("/siu/assignments/<assignmentId>/terminate")
@require_roles("SIUManager")
def terminate_assignment(assignmentId: str, _user_id: str, _role: str):
    body = get_json_body()
    require_string(body, "reason")
    assignment = path_or_404(db.assignments, assignmentId, "Assignment")
    if assignment.get("status") != "ACTIVE":
        raise_err(ERR_INVALID_STATE, "Assignment must be ACTIVE to be terminated")
    case = db.cases.get(assignment.get("case_id"))
    if case is not None and case.get("status") in CASE_TERMINAL:
        raise_err(ERR_CASE_NOT_IN_REQUIRED_STATE, "Case is in a terminal status")
    assignment["status"] = "TERMINATED"
    db.touch(assignment)
    adjust_case_count(assignment.get("investigator_id"), -1)
    if case is not None:
        case["assigned_investigator_id"] = None
        if case.get("status") == "UNDER_INVESTIGATION":
            # Bubble-up demotion: without a lead investigator the case returns to OPEN.
            case["status"] = "OPEN"
        db.touch(case)
    return success_object(pub_assignment(assignment))
