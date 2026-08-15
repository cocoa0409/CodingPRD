"""MaintenancePlan endpoints (PRD §3.7)."""
from flask import Blueprint, request

from db import children, store
from errors import (ApiError, ERR_MAINTENANCE_WINDOW_INVALID, invalid_state,
                    not_found)
from middleware import authenticate
from middleware import ROLE_FINANCE_ADMIN as FA
from middleware import ROLE_PROJECT_ENGINEER as PE
from middleware import ROLE_SITE_SUPERVISOR as SS
from middleware import ROLE_SERVICE_MANAGER as SM
from response import success, success_list
from services.domain import common_fields, compute_hours_until_due, pub, pubs, touch
from validation import as_int, body, paginate, pagination, req

bp = Blueprint("plans", __name__)

READ_ROLES = {FA, PE, SS, SM}


def get_plan(plan_id):
    m = store.plans.get(plan_id)
    if m is None:
        raise not_found("Maintenance plan not found")
    return m


@bp.post("/robotics/cell-projects/<project_id>/maintenance-plans")
def create_plan(project_id):
    authenticate({SM})
    if project_id not in store.projects:
        raise not_found("Cell project not found")
    b = body()
    plan = {
        **common_fields(),
        "cell_project_id": project_id,
        "interval_operating_hours": as_int(req(b, "interval_operating_hours"),
                                           "interval_operating_hours", 500, 10000),
        "first_due_at_hours": as_int(req(b, "first_due_at_hours"),
                                     "first_due_at_hours", min_v=0),
        "plan_status": "DRAFT",
        "current_operating_hours": 0,
        "hours_until_due": None,
    }
    store.plans[plan["id"]] = plan
    return success(pub(plan), 201)


@bp.get("/robotics/cell-projects/<project_id>/maintenance-plans")
def list_plans(project_id):
    authenticate(READ_ROLES)
    if project_id not in store.projects:
        raise not_found("Cell project not found")
    limit, offset = pagination()
    items = children("plans", "cell_project_id", project_id)
    status_filter = request.args.get("plan_status")
    if status_filter is not None:
        items = [m for m in items if m["plan_status"] == status_filter]
    page, total = paginate(items, limit, offset)
    return success_list(pubs(page), limit, offset, total)


@bp.get("/robotics/maintenance-plans/<plan_id>")
def get_one_plan(plan_id):
    authenticate(READ_ROLES)
    return success(pub(get_plan(plan_id)))


@bp.post("/robotics/maintenance-plans/<plan_id>/activate")
def activate_plan(plan_id):
    authenticate({SM})
    m = get_plan(plan_id)
    if m["plan_status"] == "DRAFT":
        project = store.projects[m["cell_project_id"]]
        if project["status"] not in ("SAT", "TRAINING", "GUARANTEE"):
            raise invalid_state(
                "Plan activation requires project status SAT, TRAINING, or GUARANTEE")
        if m["first_due_at_hours"] < m["current_operating_hours"]:
            raise ApiError(ERR_MAINTENANCE_WINDOW_INVALID, 422,
                           "first_due_at_hours is before the current meter reading")
        if not (500 <= m["interval_operating_hours"] <= 10000):
            raise ApiError(ERR_MAINTENANCE_WINDOW_INVALID, 422,
                           "interval_operating_hours is outside [500, 10000]")
    elif m["plan_status"] != "SUSPENDED":
        raise invalid_state("Only a DRAFT or SUSPENDED plan can be activated")
    m["plan_status"] = "ACTIVE"
    compute_hours_until_due(m)
    touch(m)
    return success(pub(m))


@bp.post("/robotics/maintenance-plans/<plan_id>/suspend")
def suspend_plan(plan_id):
    authenticate({SM})
    m = get_plan(plan_id)
    if m["plan_status"] != "ACTIVE":
        raise invalid_state("Only an ACTIVE plan can be suspended")
    m["plan_status"] = "SUSPENDED"
    touch(m)
    return success(pub(m))


@bp.post("/robotics/maintenance-plans/<plan_id>/meter-reading")
def meter_reading(plan_id):
    authenticate({SM})
    m = get_plan(plan_id)
    if m["plan_status"] == "CLOSED":
        raise invalid_state("A CLOSED plan cannot accept meter readings")
    b = body()
    m["current_operating_hours"] = as_int(req(b, "current_operating_hours"),
                                          "current_operating_hours", min_v=0)
    compute_hours_until_due(m)
    touch(m)
    return success(pub(m))
