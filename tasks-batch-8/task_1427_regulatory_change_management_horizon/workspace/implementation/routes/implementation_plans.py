"""Implementation plans: drafting, approval loop, deadline axis (PRD §3.6)."""

from datetime import timedelta

from flask import Blueprint, request

from db import new_id, now_clock, stamp_new, store, touch
from errors import (ApiError, ERR_DEADLINE_EXCEEDS_MANDATE,
                    ERR_DEADLINE_IN_PAST, ERR_GAP_NOT_CONFIRMED,
                    ERR_INVALID_EXTENSION, ERR_MAX_EXTENSIONS_REACHED,
                    ERR_OBLIGATION_NOT_ACTIVE, ERR_PLAN_ALREADY_EXISTS,
                    ERR_PLAN_NOT_SUBMITTED, invalid_state, not_resource_owner)
from middleware import (auth_context, get_body, get_or_404, req_dt, req_str,
                        require_roles)
from response import paginate, success_object
from serializers import created_sorted, plan_to_api
from services.audit import append_audit
from services.calculations import mandate_deadline
from services.cascades import recompute_plan_posture

bp = Blueprint("implementation_plans", __name__)

PLAN_NON_TERMINAL = ("DRAFT", "SUBMITTED", "REJECTED", "APPROVED",
                     "IN_EXECUTION", "COMPLETED")
MAX_EXTENSIONS = 2
MAX_EXTENSION_DAYS = 90


def _owned_plan(plan_id, user_id):
    plan = get_or_404(store.plans, plan_id, "implementation plan")
    if plan["business_owner_id"] != user_id:
        raise not_resource_owner()
    return plan


@bp.post("/compliance/implementation-plans")
def create_plan():
    user_id, role = auth_context()
    require_roles(role, ("BusinessOwner",))
    body = get_body()
    gap_id = req_str(body, "gap_analysis_id")
    title = req_str(body, "title")
    target = req_dt(body, "target_completion_date")

    # Priority 3: body FK existence.
    gap = get_or_404(store.gap_analyses, gap_id, "gap analysis")
    assessment = store.assessments.get(gap["impact_assessment_id"])

    # Priority 2 (ownership): caller must be the owner of the accepted
    # assessment behind the gap.
    owner_id = assessment["business_owner_id"] if assessment else None
    if user_id != owner_id:
        raise not_resource_owner()

    # Priority 6: temporal bounds.
    clock = now_clock()
    if not target > clock:
        raise ApiError(ERR_DEADLINE_IN_PAST, 422,
                       "target_completion_date is not strictly after the "
                       "logical clock")
    # The mandate counts from the gap's confirmed_at (PRD §3.6), which exists
    # only once the gap is CONFIRMED; for a non-CONFIRMED gap the mandate
    # bound is incomputable and the priority-8 ERR_GAP_NOT_CONFIRMED fires.
    if gap["status"] == "CONFIRMED":
        obligation = store.obligations.get(gap["obligation_id"])
        deadline = mandate_deadline(obligation["criticality"], gap["confirmed_at"])
        if target > deadline:
            raise ApiError(ERR_DEADLINE_EXCEEDS_MANDATE, 422,
                           "target_completion_date exceeds the "
                           "implementation_deadline mandate")

    # Priority 7: at most one non-terminal plan per gap analysis.
    if any(p["gap_analysis_id"] == gap["id"]
           and p["execution_status"] in PLAN_NON_TERMINAL
           for p in store.plans.values()):
        raise ApiError(ERR_PLAN_ALREADY_EXISTS, 409,
                       "A non-terminal implementation plan already exists for "
                       "the gap analysis")

    # Priority 8: referential state.
    if gap["status"] != "CONFIRMED":
        raise ApiError(ERR_GAP_NOT_CONFIRMED, 409,
                       "Plan creation attempted against a gap analysis not "
                       "CONFIRMED")

    plan = stamp_new({
        "id": new_id(),
        "gap_analysis_id": gap["id"],
        "title": title,
        "target_completion_date": target,
        "obligation_id": gap["obligation_id"],
        "regulatory_change_id": assessment["regulatory_change_id"],
        "business_owner_id": owner_id,
        "execution_status": "DRAFT",
        "deadline_posture": "ON_TRACK",
        "pinned_register_version_number": None,
        "extension_count": 0,
        "submitted_by_user_id": None,
        "approved_by_user_id": None,
        "verification_evidence_id": None,
    })
    store.plans[plan["id"]] = plan
    append_audit(user_id, role, "POST /compliance/implementation-plans",
                 "ImplementationPlan", plan["id"])
    return success_object(plan_to_api(plan), status=201)


@bp.get("/compliance/implementation-plans")
def list_plans():
    auth_context()
    items = created_sorted(store.plans.values())
    for param in ("gap_analysis_id", "obligation_id", "regulatory_change_id",
                  "business_owner_id", "verification_evidence_id",
                  "execution_status", "deadline_posture"):
        value = request.args.get(param)
        if value is not None:
            items = [p for p in items if p[param] == value]
    return paginate(items, plan_to_api)


@bp.get("/compliance/implementation-plans/<plan_id>")
def get_plan(plan_id):
    auth_context()
    plan = get_or_404(store.plans, plan_id, "implementation plan")
    return success_object(plan_to_api(plan))


@bp.post("/compliance/implementation-plans/<plan_id>/submit")
def submit_plan(plan_id):
    user_id, role = auth_context()
    require_roles(role, ("BusinessOwner",))
    plan = _owned_plan(plan_id, user_id)
    if plan["execution_status"] not in ("DRAFT", "REJECTED"):
        raise invalid_state("submit requires execution_status DRAFT or REJECTED")
    plan["execution_status"] = "SUBMITTED"
    plan["submitted_by_user_id"] = user_id
    touch(plan)
    append_audit(user_id, role, "POST /compliance/implementation-plans/{id}/submit",
                 "ImplementationPlan", plan["id"])
    return success_object(plan_to_api(plan))


@bp.post("/compliance/implementation-plans/<plan_id>/approve")
def approve_plan(plan_id):
    user_id, role = auth_context()
    require_roles(role, ("ComplianceManager",))
    plan = get_or_404(store.plans, plan_id, "implementation plan")
    if plan["execution_status"] != "SUBMITTED":
        raise ApiError(ERR_PLAN_NOT_SUBMITTED, 409,
                       "Plan approve attempted when execution_status != SUBMITTED")
    obligation = store.obligations.get(plan["obligation_id"])
    if obligation is None or obligation["status"] != "ACTIVE":
        raise ApiError(ERR_OBLIGATION_NOT_ACTIVE, 409,
                       "Referenced obligation is not ACTIVE")

    # Version pinning on approval.
    plan["pinned_register_version_number"] = store.register["current_version_number"]
    plan["approved_by_user_id"] = user_id
    plan["execution_status"] = "APPROVED"
    touch(plan)
    # Posture becomes live on the APPROVED axis (may spawn DEADLINE_BREACH).
    recompute_plan_posture(plan)
    append_audit(user_id, role, "POST /compliance/implementation-plans/{id}/approve",
                 "ImplementationPlan", plan["id"])
    return success_object(plan_to_api(plan))


@bp.post("/compliance/implementation-plans/<plan_id>/reject")
def reject_plan(plan_id):
    user_id, role = auth_context()
    require_roles(role, ("ComplianceManager",))
    body = get_body()
    req_str(body, "reason")
    plan = get_or_404(store.plans, plan_id, "implementation plan")
    if plan["execution_status"] != "SUBMITTED":
        raise ApiError(ERR_PLAN_NOT_SUBMITTED, 409,
                       "Plan reject attempted when execution_status != SUBMITTED")
    plan["execution_status"] = "REJECTED"
    touch(plan)
    append_audit(user_id, role, "POST /compliance/implementation-plans/{id}/reject",
                 "ImplementationPlan", plan["id"])
    return success_object(plan_to_api(plan))


@bp.post("/compliance/implementation-plans/<plan_id>/begin-execution")
def begin_execution(plan_id):
    user_id, role = auth_context()
    require_roles(role, ("BusinessOwner",))
    plan = _owned_plan(plan_id, user_id)
    if plan["execution_status"] != "APPROVED":
        raise invalid_state("begin-execution requires execution_status APPROVED")
    plan["execution_status"] = "IN_EXECUTION"
    touch(plan)
    append_audit(user_id, role,
                 "POST /compliance/implementation-plans/{id}/begin-execution",
                 "ImplementationPlan", plan["id"])
    return success_object(plan_to_api(plan))


@bp.post("/compliance/implementation-plans/<plan_id>/complete")
def complete_plan(plan_id):
    user_id, role = auth_context()
    require_roles(role, ("BusinessOwner",))
    plan = _owned_plan(plan_id, user_id)
    if plan["execution_status"] != "IN_EXECUTION":
        raise invalid_state("complete requires execution_status IN_EXECUTION")
    plan["execution_status"] = "COMPLETED"
    # deadline_posture freezes at its current value (late completion visible).
    touch(plan)
    append_audit(user_id, role, "POST /compliance/implementation-plans/{id}/complete",
                 "ImplementationPlan", plan["id"])
    return success_object(plan_to_api(plan))


@bp.post("/compliance/implementation-plans/<plan_id>/extend-deadline")
def extend_deadline(plan_id):
    user_id, role = auth_context()
    require_roles(role, ("BusinessOwner",))
    body = get_body()
    new_target = req_dt(body, "new_target_completion_date")
    req_str(body, "rationale")

    plan = _owned_plan(plan_id, user_id)
    if plan["execution_status"] not in ("APPROVED", "IN_EXECUTION"):
        raise invalid_state("extend-deadline requires execution_status APPROVED "
                            "or IN_EXECUTION")

    # Priority 6 (temporal) precedes priority 7 (structural cap) per PRD §2.10.
    current = plan["target_completion_date"]
    if not (new_target > current
            and new_target <= current + timedelta(days=MAX_EXTENSION_DAYS)):
        raise ApiError(ERR_INVALID_EXTENSION, 422,
                       "Extension target not strictly after current target or "
                       "more than 90 days beyond it")
    if plan["extension_count"] >= MAX_EXTENSIONS:
        raise ApiError(ERR_MAX_EXTENSIONS_REACHED, 422,
                       "extension_count already == 2")

    plan["target_completion_date"] = new_target
    plan["extension_count"] += 1
    touch(plan)
    # Posture recompute may recover OVERDUE -> AT_RISK / ON_TRACK.
    recompute_plan_posture(plan)

    # Granted extensions resolve standing DEADLINE_BREACH escalations.
    clock = now_clock()
    for escalation in store.escalations.values():
        if (escalation["target_type"] == "IMPLEMENTATION_PLAN"
                and escalation["target_id"] == plan["id"]
                and escalation["trigger_rule"] == "DEADLINE_BREACH"
                and escalation["status"] in ("OPEN", "ACKNOWLEDGED")):
            escalation["status"] = "RESOLVED"
            escalation["resolution_code"] = "EXTENSION_GRANTED"
            escalation["resolved_at"] = clock
            touch(escalation)

    append_audit(user_id, role,
                 "POST /compliance/implementation-plans/{id}/extend-deadline",
                 "ImplementationPlan", plan["id"])
    return success_object(plan_to_api(plan))
