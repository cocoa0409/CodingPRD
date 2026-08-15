"""Training assignments (PRD 3.2): manual assignment with duplicate /
certification-window / employee-active guards, completion, reassignment."""

from flask import Blueprint, request

import db
from clock import CLOCK
from errors import ApiError
from middleware import auth, paginate, ALL_ROLES
from response import ok, ok_list
from services import core, ops
from util import add_months

bp = Blueprint("training", __name__)

_WRITER_ROLES = ["Supervisor", "SafetyManager", "EHSAdmin"]


@bp.route("/safety/training-assignments", methods=["POST"])
def create_assignment():
    auth(_WRITER_ROLES)
    body = core.body_json()
    employee_id = core.req_str(body, "employee_id")
    course_id = core.req_str(body, "course_id")
    due_date = core.req_datetime(body, "due_date")
    emp = core.get_or_404("employees", employee_id, "Employee")
    course = core.get_or_404("training_courses", course_id, "TrainingCourse")

    # Business-constraint order (PRD 2.6): duplicate -> certification window ->
    # employee-active.
    if any(t["employee_id"] == emp["id"] and t["course_id"] == course["id"]
           and t["status"] == "ASSIGNED"
           for t in db.DB["training_assignments"].values()):
        raise ApiError("ERR_DUPLICATE_ASSIGNMENT", 409,
                       "An ASSIGNED assignment already exists for this employee + course")
    now = CLOCK.now()
    for t in db.DB["training_assignments"].values():
        if t["employee_id"] == emp["id"] and t["course_id"] == course["id"] \
                and t["status"] == "COMPLETED" and t["cert_valid_until"] is not None:
            remaining_days = (t["cert_valid_until"] - now).days
            # Strictly greater blocks; exactly the window passes.
            if remaining_days > course["renewal_window_days"]:
                raise ApiError("ERR_CERTIFICATION_ACTIVE", 409,
                               "Employee holds a live certification for this course")
    if emp["status"] != "ACTIVE":
        raise ApiError("ERR_EMPLOYEE_INACTIVE", 422,
                       "Cannot assign training to an INACTIVE employee")

    role = db.DB["job_roles"].get(emp["job_role_id"])
    required = bool(role and course["id"] in role["required_course_ids"])
    t = core.stamp_new({
        "id": core.new_id(),
        "employee_id": emp["id"],
        "course_id": course["id"],
        "due_date": due_date,
        "required": required,
        "source": "MANUAL",
        "status": "ASSIGNED",
        "completed_at": None,
        "cert_valid_until": None,
    })
    db.DB["training_assignments"][t["id"]] = t
    ops.recompute_pending_training(emp)
    return ok(core.assignment_view(t), 201)


@bp.route("/safety/training-assignments", methods=["GET"])
def list_assignments():
    auth(ALL_ROLES)
    employee_id = request.args.get("employee_id")
    course_id = request.args.get("course_id")
    status = request.args.get("status")
    required = core.parse_bool_param(request.args.get("required"), "required")
    items = list(db.DB["training_assignments"].values())
    if employee_id is not None:
        items = [t for t in items if t["employee_id"] == employee_id]
    if course_id is not None:
        items = [t for t in items if t["course_id"] == course_id]
    if status is not None:
        items = [t for t in items if t["status"] == status]
    if required is not None:
        items = [t for t in items if t["required"] is required]
    items = core.sorted_by_created(items)
    page, total, limit, offset = paginate(items)
    return ok_list([core.assignment_view(t) for t in page], total, limit, offset)


@bp.route("/safety/training-assignments/<tid>", methods=["GET"])
def get_assignment(tid):
    auth(ALL_ROLES)
    t = core.get_or_404("training_assignments", tid, "TrainingAssignment")
    return ok(core.assignment_view(t))


@bp.route("/safety/training-assignments/<tid>/complete", methods=["POST"])
def complete_assignment(tid):
    auth(_WRITER_ROLES)
    t = core.get_or_404("training_assignments", tid, "TrainingAssignment")
    body = core.body_json()
    completed_at = core.opt_datetime(body, "completed_at", default=None)
    if completed_at is None:
        completed_at = CLOCK.now()
    if t["status"] != "ASSIGNED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only an ASSIGNED assignment can be completed")
    if completed_at > CLOCK.now():
        raise ApiError("ERR_FUTURE_DATE_NOT_ALLOWED", 422,
                       "completed_at must not be in the future")
    emp = db.DB["employees"].get(t["employee_id"])
    if emp is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Employee not found")
    if emp["status"] != "ACTIVE":
        raise ApiError("ERR_EMPLOYEE_INACTIVE", 422,
                       "Cannot complete training for an INACTIVE employee")
    course = db.DB["training_courses"].get(t["course_id"])
    t["status"] = "COMPLETED"
    t["completed_at"] = completed_at
    validity = course["validity_months"] if course else 0
    t["cert_valid_until"] = add_months(completed_at, validity)
    core.touch(t)
    ops.recompute_pending_training(emp)
    return ok(core.assignment_view(t))


@bp.route("/safety/training-assignments/<tid>/reassign", methods=["POST"])
def reassign_assignment(tid):
    auth(_WRITER_ROLES)
    t = core.get_or_404("training_assignments", tid, "TrainingAssignment")
    body = core.body_json()
    due_date = core.req_datetime(body, "due_date")
    if t["status"] != "EXPIRED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only an EXPIRED assignment can be reassigned")
    t["status"] = "ASSIGNED"
    t["due_date"] = due_date
    core.touch(t)
    emp = db.DB["employees"].get(t["employee_id"])
    if emp is not None:
        ops.recompute_pending_training(emp)
    return ok(core.assignment_view(t))
