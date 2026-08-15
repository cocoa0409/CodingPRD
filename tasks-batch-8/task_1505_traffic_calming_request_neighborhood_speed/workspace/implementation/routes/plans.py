"""Treatment plans: submit, approve (3-link cascade), request revision
(PRD §3.5)."""
from flask import Blueprint, g, request

from auth import require_roles, ALL_ROLES
from calc import allocation_for
from envelope import object_response
from errors import (
    ApiError, ERR_PLAN_INVALID_STATE, ERR_APPROVER_IS_PLAN_AUTHOR,
    ERR_REBASELINE_EXCEEDS_BUDGET,
)
from helpers import get_plan, paginated
from store import store, touch

bp = Blueprint("plans", __name__)


@bp.get("/api/treatment-plans/<planId>")
@require_roles(*ALL_ROLES)
def get_one(planId):
    return object_response(get_plan(planId))


@bp.get("/api/treatment-plans")
@require_roles(*ALL_ROLES)
def list_plans():
    return paginated(list(store.plans.values()), {
        "request_id": request.args.get("request_id"),
        "status": request.args.get("status"),
    })


@bp.post("/api/treatment-plans/<planId>/submit-for-review")
@require_roles("TrafficEngineer")
def submit_for_review(planId):
    plan = get_plan(planId)
    if plan["status"] != "DRAFT":
        raise ApiError(409, ERR_PLAN_INVALID_STATE,
                       "Only a DRAFT plan can be submitted for review")
    plan["status"] = "SUBMITTED_FOR_REVIEW"
    plan["submitted_at"] = store.now
    touch(plan)
    return object_response(plan)


@bp.post("/api/treatment-plans/<planId>/approve")
@require_roles("CityEngineer")
def approve(planId):
    plan = get_plan(planId)
    # Tier 5: state gate
    if plan["status"] != "SUBMITTED_FOR_REVIEW":
        raise ApiError(409, ERR_PLAN_INVALID_STATE,
                       "Only a SUBMITTED_FOR_REVIEW plan can be approved")
    # Tier 6: segregation of duties
    if g.user_id == plan["created_by_user_id"]:
        raise ApiError(403, ERR_APPROVER_IS_PLAN_AUTHOR,
                       "The approver must not be the plan's author")
    req = store.requests[plan["request_id"]]
    cycle = store.cycles[req["funding_cycle_id"]]
    # Tier 9: re-baseline must fit the remaining budget (atomic pre-check)
    final_alloc = allocation_for(plan["estimated_cost_cents"])
    delta = final_alloc - req["allocated_cents"]
    if cycle["budget_available_cents"] < delta:
        raise ApiError(402, ERR_REBASELINE_EXCEEDS_BUDGET,
                       "Plan approval re-baseline delta exceeds the cycle's remaining budget")
    # Link 1: plan -> APPROVED
    plan["status"] = "APPROVED"
    plan["approved_at"] = store.now
    plan["approved_by_user_id"] = g.user_id
    touch(plan)
    # Link 2: request DESIGN_IN_PROGRESS -> BALLOT_READY
    req["status"] = "BALLOT_READY"
    touch(req)
    # Link 3: funding-cycle re-baseline
    cycle["budget_committed_cents"] += delta
    cycle["budget_available_cents"] = cycle["budget_total_cents"] - cycle["budget_committed_cents"]
    touch(cycle)
    req["allocated_cents"] = final_alloc
    # allocated_cents re-baseline mutates the request in the same cascade act;
    # updated_at/version were already refreshed above for this operation.
    return object_response(plan)


@bp.post("/api/treatment-plans/<planId>/request-revision")
@require_roles("CityEngineer")
def request_revision(planId):
    plan = get_plan(planId)
    if plan["status"] != "SUBMITTED_FOR_REVIEW":
        raise ApiError(409, ERR_PLAN_INVALID_STATE,
                       "Only a SUBMITTED_FOR_REVIEW plan can be sent back for revision")
    if g.user_id == plan["created_by_user_id"]:
        raise ApiError(403, ERR_APPROVER_IS_PLAN_AUTHOR,
                       "The reviewer must not be the plan's author")
    # SUBMITTED_FOR_REVIEW -> REVISION_REQUESTED -> DRAFT (automatic, PRD §3.5)
    plan["status"] = "DRAFT"
    touch(plan)
    return object_response(plan)
