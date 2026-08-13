"""Compliance assignments: create, waive (segregated), extend (OCC)."""
from flask import Blueprint, request

from auth import require_role, require_any_role
from db import store, new_resource, touch, now
from envelope import ok, paginate, get_body, sort_by_created
from errors import err, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STATE, \
    ERR_SEGREGATION_OF_DUTIES, ERR_STALE_ASSIGNMENT_VERSION
from serializers import ser_assignment
from validate import req_str, req_datetime, req_int

bp = Blueprint("compliance", __name__)


def get_assignment_or_404(aid):
    a = store.assignments.get(aid)
    if a is None:
        raise err(ERR_NOT_FOUND, "compliance assignment not found")
    return a


@bp.post("/pd/compliance-assignments")
def create_assignment():
    ctx = require_role("PDCoordinator")
    body = get_body()
    employee_id = req_str(body, "employee_id")
    course_id = req_str(body, "course_id")
    due = req_datetime(body, "due_date")
    if employee_id not in store.employees:
        raise err(ERR_NOT_FOUND, "employee_id not found")
    course = store.courses.get(course_id)
    if course is None:
        raise err(ERR_NOT_FOUND, "course_id not found")
    if course["compliance_tag"] is None:
        raise err(ERR_INVALID_REQUEST,
                  "course_id must reference a compliance-tagged course")
    a = new_resource()
    a.update({
        "employee_id": employee_id,
        "course_id": course_id,
        "due_date": due,
        "status": "ASSIGNED",
        "assigned_by_user_id": ctx.user_id,
        "satisfied_at": None,
        "extension_count": 0,
    })
    store.assignments[a["id"]] = a
    return ok(ser_assignment(a), 201)


@bp.get("/pd/compliance-assignments/<aid>")
def get_assignment(aid):
    require_any_role()
    return ok(ser_assignment(get_assignment_or_404(aid)), 200)


@bp.get("/pd/compliance-assignments")
def list_assignments():
    require_any_role()
    items = store.assignments.values()
    for key in ("employee_id", "course_id", "status"):
        v = request.args.get(key)
        if v is not None:
            items = [a for a in items if a[key] == v]
    return paginate([ser_assignment(a) for a in sort_by_created(items)])


@bp.post("/pd/compliance-assignments/<aid>/waive")
def waive_assignment(aid):
    ctx = require_role("PDCoordinator")
    a = get_assignment_or_404(aid)
    body = get_body()
    req_str(body, "reason")
    if a["status"] not in ("ASSIGNED", "IN_PROGRESS", "OVERDUE", "ESCALATED"):
        raise err(ERR_INVALID_STATE,
                  "assignment cannot be waived from this state")
    if ctx.user_id == a["assigned_by_user_id"]:
        raise err(ERR_SEGREGATION_OF_DUTIES,
                  "the creator cannot waive this assignment")
    a["status"] = "WAIVED"
    touch(a)
    # standing recomputes on read
    return ok(ser_assignment(a), 200)


@bp.post("/pd/compliance-assignments/<aid>/extend")
def extend_assignment(aid):
    require_role("PDCoordinator")
    a = get_assignment_or_404(aid)
    body = get_body()
    new_due = req_datetime(body, "new_due_date")
    expected = req_int(body, "expected_assignment_version")
    if a["status"] not in ("ASSIGNED", "IN_PROGRESS", "OVERDUE"):
        raise err(ERR_INVALID_STATE,
                  "assignment cannot be extended from this state")
    if not (new_due > now()):
        raise err(ERR_INVALID_REQUEST, "new_due_date must be in the future")
    if expected != a["version"]:
        raise err(ERR_STALE_ASSIGNMENT_VERSION,
                  "expected_assignment_version does not match the assignment")
    a["due_date"] = new_due
    a["status"] = "ASSIGNED"
    a["extension_count"] += 1
    touch(a)
    return ok(ser_assignment(a), 200)
