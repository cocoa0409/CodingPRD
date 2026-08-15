"""Workforce roster (PRD 3.2): employee creation with automatic required
training assignment, and deactivation with open-training cancellation."""

from datetime import timedelta

from flask import Blueprint, request

import db
from clock import CLOCK
from middleware import auth, paginate, ALL_ROLES
from response import ok, ok_list
from services import core, ops

bp = Blueprint("employees", __name__)


@bp.route("/safety/employees", methods=["POST"])
def create_employee():
    auth(["EHSAdmin"])
    body = core.body_json()
    full_name = core.req_str(body, "full_name")
    job_role_id = core.req_str(body, "job_role_id")
    hired_on = core.req_date(body, "hired_on")
    committee_member = core.opt_bool(body, "committee_member", default=False)
    role = core.get_or_404("job_roles", job_role_id, "JobRole")

    e = core.stamp_new({
        "id": core.new_id(),
        "full_name": full_name,
        "job_role_id": role["id"],
        "hired_on": hired_on.isoformat(),
        "committee_member": committee_member,
        "status": "ACTIVE",
        "pending_required_training_count": 0,
    })
    db.DB["employees"][e["id"]] = e

    # Auto-create SYSTEM_JOB_HAZARD assignments for every required course;
    # due = logical now + 30 days (PRD 3.2).
    for course_id in role["required_course_ids"]:
        t = core.stamp_new({
            "id": core.new_id(),
            "employee_id": e["id"],
            "course_id": course_id,
            "due_date": CLOCK.now() + timedelta(days=30),
            "required": True,
            "source": "SYSTEM_JOB_HAZARD",
            "status": "ASSIGNED",
            "completed_at": None,
            "cert_valid_until": None,
        })
        db.DB["training_assignments"][t["id"]] = t
    ops.recompute_pending_training(e)
    return ok(core.employee_view(e), 201)


@bp.route("/safety/employees", methods=["GET"])
def list_employees():
    auth(ALL_ROLES)
    job_role_id = request.args.get("job_role_id")
    status = request.args.get("status")
    committee = core.parse_bool_param(request.args.get("committee_member"),
                                      "committee_member")
    items = list(db.DB["employees"].values())
    if job_role_id is not None:
        items = [e for e in items if e["job_role_id"] == job_role_id]
    if status is not None:
        items = [e for e in items if e["status"] == status]
    if committee is not None:
        items = [e for e in items if e["committee_member"] is committee]
    items = core.sorted_by_created(items)
    page, total, limit, offset = paginate(items)
    return ok_list([core.employee_view(e) for e in page], total, limit, offset)


@bp.route("/safety/employees/<eid>", methods=["GET"])
def get_employee(eid):
    auth(ALL_ROLES)
    e = core.get_or_404("employees", eid, "Employee")
    return ok(core.employee_view(e))


@bp.route("/safety/employees/<eid>/deactivate", methods=["POST"])
def deactivate_employee(eid):
    auth(["EHSAdmin"])
    e = core.get_or_404("employees", eid, "Employee")
    core.body_json()
    if e["status"] != "ACTIVE":
        from errors import ApiError
        raise ApiError("ERR_INVALID_STATE", 409, "Employee is not ACTIVE")
    e["status"] = "INACTIVE"
    core.touch(e)
    # Cascade: every ASSIGNED | EXPIRED assignment of this employee is cancelled.
    for t in db.DB["training_assignments"].values():
        if t["employee_id"] == e["id"] and t["status"] in ("ASSIGNED", "EXPIRED"):
            t["status"] = "CANCELLED"
            core.touch(t)
    ops.recompute_pending_training(e)
    return ok(core.employee_view(e))
