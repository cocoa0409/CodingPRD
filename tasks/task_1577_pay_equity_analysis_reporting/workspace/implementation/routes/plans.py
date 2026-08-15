"""RemediationPlan endpoints (PRD §3.4)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_RATIONALE_REQUIRED,
    ERR_STUDY_NOT_IN_REMEDIATION,
    ERR_ACTIVE_PLAN_EXISTS,
    ERR_PLAN_INVALID_STATE,
    ERR_PLAN_EMPTY,
)
from middleware import authorized
from response import success_object
from routes.helpers import get_one, list_response, public
from services.calculations import compute_suggested_allocation
from services.core import new_record, touch, plans_of_study, adjustments_of_plan
from validate import get_body, req_int, opt_enum, require_path_resource, require_fk

bp = Blueprint("plans", __name__)

ALLOCATION_STRATEGIES = {"FULL_CLOSURE", "PRO_RATA"}


@bp.post("/remediation-plans")
def create_plan():
    caller = authorized(["CompAnalyst"])
    body = get_body()
    study_id = body.get("study_id")
    if study_id is None or not isinstance(study_id, str) or study_id.strip() == "":
        raise_error(ERR_INVALID_REQUEST, "missing or invalid field: study_id")
    # Priority 3: body FK existence
    study = require_fk("pay_equity_studies", study_id, "study_id")
    # Priority 3.7: shape
    total_budget_cents = req_int(body, "total_budget_cents")
    if total_budget_cents <= 0:
        raise_error(ERR_INVALID_REQUEST, "total_budget_cents must be > 0")
    allocation_strategy = opt_enum(body, "allocation_strategy",
                                   ALLOCATION_STRATEGIES, "FULL_CLOSURE")
    # Priority 4: state
    if study["status"] != "REMEDIATION_OPEN":
        raise_error(ERR_STUDY_NOT_IN_REMEDIATION,
                    "plan creation requires the study to be REMEDIATION_OPEN")
    # Priority 7: at most one non-COMPLETED plan per study
    for p in plans_of_study(study_id):
        if p["status"] != "COMPLETED":
            raise_error(ERR_ACTIVE_PLAN_EXISTS,
                        "study already has a non-COMPLETED remediation plan")

    rec = new_record("remediation_plans", {
        "study_id": study_id,
        "total_budget_cents": total_budget_cents,
        "allocation_strategy": allocation_strategy,
        "committed_cents": 0,
        "remaining_cents": total_budget_cents,
        "rejection_count": 0,
        "status": "DRAFT",
        "created_by_user_id": caller.user_id,
    })
    return success_object(public(rec), status=201)


@bp.get("/remediation-plans")
def list_plans():
    return list_response("remediation_plans", {
        "study_id": request.args.get("study_id"),
        "status": request.args.get("status"),
    })


@bp.get("/remediation-plans/<rid>")
def get_plan(rid):
    return get_one("remediation_plans", rid)


@bp.get("/remediation-plans/<rid>/suggested-allocation")
def suggested_allocation(rid):
    authorized(["CompAnalyst", "RemediationApprover"])
    plan = require_path_resource("remediation_plans", rid)
    return success_object(compute_suggested_allocation(plan))


@bp.post("/remediation-plans/<rid>/submit")
def submit_plan(rid):
    authorized(["CompAnalyst"])
    plan = require_path_resource("remediation_plans", rid)
    # Priority 4: state
    if plan["status"] != "DRAFT":
        raise_error(ERR_PLAN_INVALID_STATE, "submit requires a DRAFT plan")
    # Priority 7: plan non-empty at submit
    proposed = [a for a in adjustments_of_plan(rid) if a["status"] == "PROPOSED"]
    if not proposed:
        raise_error(ERR_PLAN_EMPTY,
                    "submit requires at least one PROPOSED adjustment")
    plan["status"] = "SUBMITTED"
    touch(plan)
    return success_object(public(plan))


@bp.post("/remediation-plans/<rid>/decision")
def decide_plan(rid):
    authorized(["RemediationApprover"])
    plan = require_path_resource("remediation_plans", rid)
    body = get_body()
    # Priority 3.7 (shape) before priority 4 (state) per PRD §2.8
    decision = body.get("decision")
    if decision not in ("APPROVE", "REJECT"):
        raise_error(ERR_INVALID_REQUEST, "decision must be APPROVE or REJECT")
    rationale = body.get("rationale")
    if decision == "REJECT":
        if rationale is None or not isinstance(rationale, str) or rationale.strip() == "":
            raise_error(ERR_RATIONALE_REQUIRED, "rationale is required for REJECT")
    # Priority 4: state
    if plan["status"] != "SUBMITTED":
        raise_error(ERR_PLAN_INVALID_STATE, "plan decision requires a SUBMITTED plan")

    if decision == "APPROVE":
        plan["status"] = "APPROVED"
    else:
        plan["status"] = "DRAFT"
        plan["rejection_count"] = plan.get("rejection_count", 0) + 1
    touch(plan)
    return success_object(public(plan))
