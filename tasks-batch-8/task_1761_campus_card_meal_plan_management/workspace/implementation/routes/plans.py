"""MealPlan endpoints (PRD 3.3)."""

from flask import Blueprint, request

from db import store
from errors import (
    err, ERR_VALIDATION, ERR_NOT_FOUND, ERR_DUPLICATE_NATURAL_KEY,
    ERR_INVALID_STATE_TRANSITION, ERR_PLAN_IN_USE,
)
from middleware import (
    authenticate, require_roles, get_body, v_str, v_int, v_bool,
    find_or_404, pub, paginate, HOLDER_TYPES,
)
from response import success
from services.core import new_row, touch

bp = Blueprint("plans", __name__)


@bp.route("/api/meal-plans", methods=["POST"])
def create_plan():
    authenticate()
    require_roles("DiningServicesManager")
    body = get_body()
    plan_code = v_str(body, "plan_code")
    name = v_str(body, "name")
    weekly_swipe_allowance = v_int(body, "weekly_swipe_allowance", min_v=0)
    dining_dollar_allocation_cents = v_int(
        body, "dining_dollar_allocation_cents", min_v=0)
    price_cents = v_int(body, "price_cents", min_v=1)
    is_unlimited_swipes = v_bool(body, "is_unlimited_swipes", default=False)
    requires_on_campus_housing = v_bool(
        body, "requires_on_campus_housing", default=False)
    eligible = body.get("eligible_holder_types")
    if (not isinstance(eligible, list) or len(eligible) == 0
            or any(not isinstance(e, str) or e not in HOLDER_TYPES for e in eligible)):
        err(ERR_VALIDATION,
            "eligible_holder_types must be a non-empty subset of the holder_type enum")
    for p in store.plans.values():
        if p["plan_code"] == plan_code:
            err(ERR_DUPLICATE_NATURAL_KEY, "plan_code already exists")
    plan = new_row()
    plan.update({
        "plan_code": plan_code,
        "name": name,
        "weekly_swipe_allowance": weekly_swipe_allowance,
        "is_unlimited_swipes": is_unlimited_swipes,
        "dining_dollar_allocation_cents": dining_dollar_allocation_cents,
        "price_cents": price_cents,
        "requires_on_campus_housing": requires_on_campus_housing,
        "eligible_holder_types": list(eligible),
        "status": "DRAFT",
    })
    store.plans[plan["id"]] = plan
    return success(pub(plan), 201)


@bp.route("/api/meal-plans", methods=["GET"])
def list_plans():
    authenticate()
    require_roles("PlatformAdmin", "CardOfficeAdmin", "DiningServicesManager",
                  "BursarOffice", "CardHolder")
    rows = list(store.plans.values())
    status = request.args.get("status")
    if status is not None:
        rows = [p for p in rows if p["status"] == status]
    data, page = paginate(rows)
    return success(data, 200, page)


@bp.route("/api/meal-plans/<pid>", methods=["GET"])
def get_plan(pid):
    authenticate()
    require_roles("PlatformAdmin", "CardOfficeAdmin", "DiningServicesManager",
                  "BursarOffice", "CardHolder")
    plan = find_or_404(store.plans, pid)
    return success(pub(plan), 200)


@bp.route("/api/meal-plans/<pid>/publish", methods=["POST"])
def publish_plan(pid):
    authenticate()
    require_roles("DiningServicesManager")
    plan = find_or_404(store.plans, pid)
    if plan["status"] != "DRAFT":
        err(ERR_INVALID_STATE_TRANSITION, "Only a DRAFT plan can be published")
    plan["status"] = "PUBLISHED"
    touch(plan)
    return success(pub(plan), 200)


@bp.route("/api/meal-plans/<pid>/retire", methods=["POST"])
def retire_plan(pid):
    authenticate()
    require_roles("DiningServicesManager")
    plan = find_or_404(store.plans, pid)
    if plan["status"] != "PUBLISHED":
        err(ERR_INVALID_STATE_TRANSITION, "Only a PUBLISHED plan can be retired")
    for enr in store.enrollments.values():
        if enr["plan_id"] == plan["id"] and enr["status"] in ("ASSIGNED", "ACTIVE"):
            err(ERR_PLAN_IN_USE,
                "The plan has ASSIGNED or ACTIVE enrollments referencing it")
    plan["status"] = "RETIRED"
    touch(plan)
    return success(pub(plan), 200)
