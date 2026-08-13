"""Individual growth plans (OCC-guarded create, supersede cascade)."""
from flask import Blueprint, request

from auth import require_role, require_any_role
from db import store, new_resource, touch
from envelope import ok, paginate, get_body, sort_by_created
from errors import err, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STATE, \
    ERR_EMPLOYEE_NOT_ACTIVE, ERR_NOT_RESOURCE_OWNER, \
    ERR_BUILDING_SCOPE_VIOLATION, ERR_STALE_EMPLOYEE_VERSION
from serializers import ser_plan, ser_entry
from validate import req_str, req_number, req_int, parse_school_year

bp = Blueprint("plans", __name__)


def get_plan_or_404(pid):
    p = store.growth_plans.get(pid)
    if p is None:
        raise err(ERR_NOT_FOUND, "growth plan not found")
    return p


@bp.post("/pd/growth-plans")
def create_plan():
    ctx = require_role("Teacher", "PDCoordinator")
    body = get_body()
    # shape (4)
    teacher_id = req_str(body, "teacher_id")
    school_year = req_str(body, "school_year")
    parse_school_year(school_year)
    focus = body.get("focus_areas")
    if (not isinstance(focus, list) or len(focus) == 0
            or any(not isinstance(x, str) for x in focus)):
        raise err(ERR_INVALID_REQUEST, "focus_areas must be a non-empty array of strings")
    target = req_number(body, "target_credits", gt=0)
    expected_version = req_int(body, "expected_employee_version")
    # FK (5)
    emp = store.employees.get(teacher_id)
    if emp is None:
        raise err(ERR_NOT_FOUND, "teacher_id not found")
    # state (6)
    if emp["status"] != "ACTIVE":
        raise err(ERR_EMPLOYEE_NOT_ACTIVE, "employee is not ACTIVE")
    # ownership (8)
    if ctx.role == "Teacher" and ctx.user_id != teacher_id:
        raise err(ERR_NOT_RESOURCE_OWNER, "teachers create only their own plans")
    # OCC (12)
    if expected_version != emp["version"]:
        raise err(ERR_STALE_EMPLOYEE_VERSION,
                  "expected_employee_version does not match the employee")
    # supersede the existing non-terminal plan for (teacher, school_year)
    for p in store.growth_plans.values():
        if (p["teacher_id"] == teacher_id and p["school_year"] == school_year
                and p["status"] in ("DRAFT", "SUBMITTED", "APPROVED",
                                    "FULFILLED")):
            p["status"] = "SUPERSEDED"
            touch(p)
    p = new_resource()
    p.update({
        "teacher_id": teacher_id,
        "school_year": school_year,
        "focus_areas": list(focus),
        "target_credits": target,
        "status": "DRAFT",
    })
    store.growth_plans[p["id"]] = p
    touch(emp)  # plan creation bumps the teacher's Employee.version
    return ok(ser_plan(p), 201)


@bp.get("/pd/growth-plans/<pid>")
def get_plan(pid):
    require_any_role()
    return ok(ser_plan(get_plan_or_404(pid)), 200)


@bp.get("/pd/growth-plans")
def list_plans():
    require_any_role()
    items = store.growth_plans.values()
    for key in ("teacher_id", "school_year", "status"):
        v = request.args.get(key)
        if v is not None:
            items = [p for p in items if p[key] == v]
    return paginate([ser_plan(p) for p in sort_by_created(items)])


@bp.get("/pd/growth-plans/<pid>/transcript-entries")
def plan_entries(pid):
    require_any_role()
    p = get_plan_or_404(pid)
    items = [e for e in store.transcript_entries.values()
             if e.get("growth_plan_id") == p["id"]]
    return paginate([ser_entry(e) for e in sort_by_created(items)])


@bp.post("/pd/growth-plans/<pid>/submit")
def submit_plan(pid):
    ctx = require_role("Teacher", "PDCoordinator")
    get_body()
    p = get_plan_or_404(pid)
    if p["status"] != "DRAFT":
        raise err(ERR_INVALID_STATE, "only a DRAFT plan can be submitted")
    if ctx.role == "Teacher" and ctx.user_id != p["teacher_id"]:
        raise err(ERR_NOT_RESOURCE_OWNER, "not your plan")
    p["status"] = "SUBMITTED"
    touch(p)
    return ok(ser_plan(p), 200)


def _check_plan_scope(ctx, p):
    teacher = store.employees.get(p["teacher_id"])
    building = teacher["primary_building_id"] if teacher else None
    if ctx.employee["primary_building_id"] != building:
        raise err(ERR_BUILDING_SCOPE_VIOLATION,
                  "plan is outside the admin's building")


@bp.post("/pd/growth-plans/<pid>/approve")
def approve_plan(pid):
    ctx = require_role("BuildingAdmin")
    get_body()
    p = get_plan_or_404(pid)
    if p["status"] != "SUBMITTED":
        raise err(ERR_INVALID_STATE, "only a SUBMITTED plan can be approved")
    _check_plan_scope(ctx, p)
    p["status"] = "APPROVED"
    touch(p)
    return ok(ser_plan(p), 200)


@bp.post("/pd/growth-plans/<pid>/return")
def return_plan(pid):
    ctx = require_role("BuildingAdmin")
    p = get_plan_or_404(pid)
    body = get_body()
    req_str(body, "reason")
    if p["status"] != "SUBMITTED":
        raise err(ERR_INVALID_STATE, "only a SUBMITTED plan can be returned")
    _check_plan_scope(ctx, p)
    p["status"] = "DRAFT"
    touch(p)
    return ok(ser_plan(p), 200)


@bp.post("/pd/growth-plans/<pid>/close")
def close_plan(pid):
    require_role("PDCoordinator")
    get_body()
    p = get_plan_or_404(pid)
    if p["status"] not in ("APPROVED", "FULFILLED"):
        raise err(ERR_INVALID_STATE,
                  "only an APPROVED or FULFILLED plan can be closed")
    p["status"] = "CLOSED"
    touch(p)
    return ok(ser_plan(p), 200)
