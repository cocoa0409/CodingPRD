"""CarePlan + CareTask endpoints (PRD §3.3)."""
from flask import Blueprint

import db
import errors
from errors import ApiError
from middleware import get_auth, require_roles
from response import success, list_success
from services import requtil
from services.lookup import get_client, get_care_plan, get_care_task

bp = Blueprint("care_plans", __name__)

READ_ROLES = {"AgencyAdmin", "Scheduler", "BillingClerk", "Caregiver"}


def _active_task_count(plan_id):
    return sum(
        1 for t in db.care_tasks.values()
        if t["care_plan_id"] == plan_id and t["status"] == "ACTIVE"
    )


@bp.post("/clients/<cid>/care-plans")
def create_care_plan(cid):
    _, role = get_auth()
    require_roles(role, {"AgencyAdmin", "Scheduler"})
    client = get_client(cid)
    body = requtil.get_body()
    title = requtil.require_str(body, "title")

    plan = {
        "client_id": client["id"],
        "title": title,
        "status": "DRAFT",
        "task_count": 0,
    }
    db.stamp_new(plan)
    db.care_plans[plan["id"]] = plan
    return success(db.public(plan), status=201)


@bp.get("/clients/<cid>/care-plans")
def list_care_plans(cid):
    _, role = get_auth()
    require_roles(role, READ_ROLES)
    client = get_client(cid)
    limit, offset = requtil.pagination()
    items = [p for p in db.care_plans.values() if p["client_id"] == client["id"]]
    page, total = requtil.paginate(items, limit, offset)
    return list_success([db.public(p) for p in page], limit, offset, total)


@bp.get("/care-plans/<pid>")
def get_care_plan_route(pid):
    _, role = get_auth()
    require_roles(role, READ_ROLES)
    plan = get_care_plan(pid)
    return success(db.public(plan))


@bp.post("/care-plans/<pid>/transition")
def transition_care_plan(pid):
    _, role = get_auth()
    require_roles(role, {"AgencyAdmin", "Scheduler"})
    plan = get_care_plan(pid)
    body = requtil.get_body()
    action = requtil.require_enum(body, "action", {"PUBLISH", "RETIRE"})

    if action == "PUBLISH":
        if plan["status"] != "DRAFT":
            raise ApiError(errors.ERR_INVALID_STATE, 409, "PUBLISH requires DRAFT")
        plan["status"] = "PUBLISHED"
    elif action == "RETIRE":
        if plan["status"] != "PUBLISHED":
            raise ApiError(errors.ERR_INVALID_STATE, 409, "RETIRE requires PUBLISHED")
        plan["status"] = "RETIRED"

    db.touch(plan)
    return success(db.public(plan))


@bp.post("/care-plans/<pid>/tasks")
def create_care_task(pid):
    _, role = get_auth()
    require_roles(role, {"AgencyAdmin", "Scheduler"})
    plan = get_care_plan(pid)
    body = requtil.get_body()
    category = requtil.require_enum(body, "category", {"ADL", "IADL"})
    name = requtil.require_str(body, "name")
    requires_companion_errand = requtil.optional_bool(body, "requires_companion_errand", False)

    task = {
        "care_plan_id": plan["id"],
        "category": category,
        "name": name,
        "requires_companion_errand": requires_companion_errand,
        "status": "ACTIVE",
    }
    db.stamp_new(task)
    db.care_tasks[task["id"]] = task

    plan["task_count"] = _active_task_count(plan["id"])
    db.touch(plan)
    return success(db.public(task), status=201)


@bp.get("/care-plans/<pid>/tasks")
def list_care_tasks(pid):
    _, role = get_auth()
    require_roles(role, READ_ROLES)
    plan = get_care_plan(pid)
    limit, offset = requtil.pagination()
    items = [t for t in db.care_tasks.values() if t["care_plan_id"] == plan["id"]]
    page, total = requtil.paginate(items, limit, offset)
    return list_success([db.public(t) for t in page], limit, offset, total)


@bp.delete("/care-plans/<pid>/tasks/<tid>")
def delete_care_task(pid, tid):
    _, role = get_auth()
    require_roles(role, {"AgencyAdmin", "Scheduler"})
    plan = get_care_plan(pid)
    task = get_care_task(plan["id"], tid)

    if task["status"] != "REMOVED":
        task["status"] = "REMOVED"
        db.touch(task)
        plan["task_count"] = _active_task_count(plan["id"])
        db.touch(plan)
    return success(db.public(task))
