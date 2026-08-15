"""Action plan routes (PRD §3.2)."""
from flask import Blueprint

import db
from auth import (
    ROLE_CREDIT_COMMITTEE, ROLE_LOAN_ACCOUNTING, ROLE_PORTFOLIO_ANALYST,
    ROLE_SPECIAL_ASSETS_MANAGER, ROLE_SYSTEM_ADMIN, ROLE_WORKOUT_OFFICER,
    require_roles,
)
from db import STORE
from errors import (
    ApiError, ERR_ACTIVE_PLAN_EXISTS, ERR_CASE_NOT_WATCHLIST,
    ERR_INVALID_TEMPORAL, ERR_NOT_FOUND, ERR_PLAN_NOT_DRAFT,
    ERR_PLAN_NOT_REJECTED, ERR_PLAN_NOT_SUBMITTED, ERR_SOD, ERR_STALE_VERSION,
    invalid_request,
)
from response import ok, paginate
from services import get_loan, get_plan, plan_out, plans_of_case, sorted_rows
from validate import as_datetime, as_int, as_str, field, get_body, no_unknown

bp = Blueprint("plans", __name__)

PLAN_READERS = (
    ROLE_WORKOUT_OFFICER, ROLE_SPECIAL_ASSETS_MANAGER, ROLE_CREDIT_COMMITTEE,
    ROLE_LOAN_ACCOUNTING, ROLE_PORTFOLIO_ANALYST, ROLE_SYSTEM_ADMIN,
)


def resolve(loanId, caseId, planId=None):
    loan = get_loan(loanId)
    if loan is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Loan not found")
    case = STORE["cases"].get(caseId)
    if case is None or case["loan_id"] != loanId:
        raise ApiError(ERR_NOT_FOUND, 404, "Workout case not found")
    plan = None
    if planId is not None:
        plan = get_plan(planId)
        if plan is None or plan["case_id"] != caseId:
            raise ApiError(ERR_NOT_FOUND, 404, "Action plan not found")
    return loan, case, plan


@bp.route("/loans/<loanId>/workout-cases/<caseId>/action-plans", methods=["POST"])
def create_plan(loanId, caseId):
    user_id, _ = require_roles(ROLE_WORKOUT_OFFICER)
    loan, case, _ = resolve(loanId, caseId)
    data = get_body()
    no_unknown(data, {
        "plan_text", "target_resolution_date", "milestone_count",
        "supersedes_plan_id", "expected_case_version",
    })
    plan_text = as_str(field(data, "plan_text"), "plan_text")
    target_raw, target_dt = as_datetime(
        field(data, "target_resolution_date"), "target_resolution_date"
    )
    milestones = as_int(field(data, "milestone_count"), "milestone_count", 1)
    supersedes = as_str(field(data, "supersedes_plan_id", ""), "supersedes_plan_id")
    expected = as_int(field(data, "expected_case_version"), "expected_case_version")

    # body reference existence (priority 3)
    existing_plans = plans_of_case(caseId)
    if supersedes != "":
        ref = get_plan(supersedes)
        if ref is None or ref["case_id"] != caseId:
            raise ApiError(ERR_NOT_FOUND, 404, "supersedes_plan_id does not resolve")
    # state (priority 4): the very first plan requires a WATCHLIST case
    if not existing_plans and case["status"] != "WATCHLIST":
        raise ApiError(ERR_CASE_NOT_WATCHLIST, 409, "Case is not WATCHLIST")
    # OCC (priority 5)
    if expected != case["version"]:
        raise ApiError(ERR_STALE_VERSION, 412, "Stale case version")
    # segregation of duties (priority 6): only the owning officer drafts
    if user_id != case["case_officer_id"]:
        raise ApiError(ERR_SOD, 403, "Only the case officer may draft plans")
    # structural: every plan after the first names its predecessor
    if existing_plans and supersedes == "":
        raise invalid_request(
            "supersedes_plan_id is required for every plan after the first"
        )
    # temporal (priority 10): target date strictly after the logical clock
    if target_dt <= db.logical_now():
        raise ApiError(
            ERR_INVALID_TEMPORAL, 422,
            "target_resolution_date must be strictly after the current time",
        )

    plan = db.stamp({
        "id": db.new_id(),
        "case_id": caseId,
        "plan_text": plan_text,
        "target_resolution_date": target_raw,
        "milestone_count": milestones,
        "supersedes_plan_id": supersedes,
        "approval_round": 0,
        "status": "DRAFT",
    })
    STORE["plans"][plan["id"]] = plan
    if case["status"] == "WATCHLIST":
        case["status"] = "ACTION_PLAN"
    db.touch(case)
    return ok(plan_out(plan), 201)


@bp.route("/loans/<loanId>/workout-cases/<caseId>/action-plans", methods=["GET"])
def list_plans(loanId, caseId):
    require_roles(*PLAN_READERS)
    resolve(loanId, caseId)
    rows = [plan_out(p) for p in sorted_rows(plans_of_case(caseId))]
    return paginate(rows)


@bp.route(
    "/loans/<loanId>/workout-cases/<caseId>/action-plans/<planId>/submit",
    methods=["POST"],
)
def submit_plan(loanId, caseId, planId):
    user_id, _ = require_roles(ROLE_WORKOUT_OFFICER)
    _, case, plan = resolve(loanId, caseId, planId)
    if plan["status"] != "DRAFT":
        raise ApiError(ERR_PLAN_NOT_DRAFT, 409, "Plan is not DRAFT")
    if user_id != case["case_officer_id"]:
        raise ApiError(ERR_SOD, 403, "Only the case officer may submit plans")
    plan["status"] = "SUBMITTED"
    db.touch(plan)
    return ok(plan_out(plan))


@bp.route(
    "/loans/<loanId>/workout-cases/<caseId>/action-plans/<planId>/approve",
    methods=["POST"],
)
def approve_plan(loanId, caseId, planId):
    user_id, _ = require_roles(ROLE_SPECIAL_ASSETS_MANAGER)
    loan, case, plan = resolve(loanId, caseId, planId)
    if plan["status"] != "SUBMITTED":
        raise ApiError(ERR_PLAN_NOT_SUBMITTED, 409, "Plan is not SUBMITTED")
    if user_id == case["case_officer_id"]:
        raise ApiError(
            ERR_SOD, 403, "Plan approver must differ from the case officer"
        )
    # exactly one active plan: another APPROVED plan blocks, unless this plan
    # supersedes it (the predecessor flips to SUPERSEDED in the same breath)
    predecessor = None
    for other in plans_of_case(caseId):
        if other["id"] != plan["id"] and other["status"] == "APPROVED":
            if plan["supersedes_plan_id"] == other["id"]:
                predecessor = other
            else:
                raise ApiError(
                    ERR_ACTIVE_PLAN_EXISTS, 409,
                    "Another action plan on the case is already APPROVED",
                )
    plan["status"] = "APPROVED"
    plan["approval_round"] += 1
    db.touch(plan)
    if predecessor is not None:
        predecessor["status"] = "SUPERSEDED"
        db.touch(predecessor)
    if case["status"] == "ACTION_PLAN":
        case["status"] = "NEGOTIATION"
        case["tdr_status"] = "PENDING_EVALUATION"
        db.touch(case)
        if loan["status"] == "WATCHLIST":
            loan["status"] = "WORKOUT"
            db.touch(loan)
    return ok(plan_out(plan))


@bp.route(
    "/loans/<loanId>/workout-cases/<caseId>/action-plans/<planId>/reject",
    methods=["POST"],
)
def reject_plan(loanId, caseId, planId):
    require_roles(ROLE_SPECIAL_ASSETS_MANAGER)
    _, _, plan = resolve(loanId, caseId, planId)
    if plan["status"] != "SUBMITTED":
        raise ApiError(ERR_PLAN_NOT_SUBMITTED, 409, "Plan is not SUBMITTED")
    plan["status"] = "REJECTED"
    plan["approval_round"] += 1
    db.touch(plan)
    return ok(plan_out(plan))


@bp.route(
    "/loans/<loanId>/workout-cases/<caseId>/action-plans/<planId>/revise",
    methods=["POST"],
)
def revise_plan(loanId, caseId, planId):
    require_roles(ROLE_WORKOUT_OFFICER)
    _, _, plan = resolve(loanId, caseId, planId)
    if plan["status"] != "REJECTED":
        raise ApiError(ERR_PLAN_NOT_REJECTED, 409, "Plan is not REJECTED")
    plan["status"] = "DRAFT"
    db.touch(plan)
    return ok(plan_out(plan))
