"""Employee routes (evaluator + mentor staff records)."""

from flask import Blueprint, request, g

from db import db
from errors import err_validation
from middleware import require_auth
from response import success_object, success_list
from services.domain import (
    get_season,
    get_employee,
    employee_view,
    interview_slot_view,
    evaluation_view,
    project_assignment_view,
)
from utils import (
    parse_pagination,
    require_string,
    optional_string,
    optional_int,
    optional_bool,
    stamp_new,
)

bp = Blueprint("employees", __name__)


@bp.route("/seasons/<sid>/employees", methods=["POST"])
@require_auth(["RecruitingAdmin"])
def create_employee(sid):
    get_season(sid)
    payload = request.get_json(silent=True) or {}
    full_name = require_string(payload, "full_name")
    email = require_string(payload, "email")
    alma_mater_school_name = optional_string(payload, "alma_mater_school_name", default=None)
    daily_slot_limit = optional_int(payload, "daily_slot_limit", default=6, min_value=1)
    max_interns = optional_int(payload, "max_interns", default=2, min_value=1)
    can_evaluate = optional_bool(payload, "can_evaluate", default=True)
    can_mentor = optional_bool(payload, "can_mentor", default=True)
    calibrated = optional_bool(payload, "calibrated", default=False)

    # Email unique within season
    for e in db.employees.values():
        if e["season_id"] == sid and e["email"] == email:
            raise err_validation(f"Employee email {email} already registered in season")

    e = {
        "season_id": sid,
        "full_name": full_name,
        "email": email,
        "alma_mater_school_name": alma_mater_school_name,
        "daily_slot_limit": daily_slot_limit,
        "max_interns": max_interns,
        "can_evaluate": can_evaluate,
        "can_mentor": can_mentor,
        "calibrated": calibrated,
        "assigned_intern_count": 0,
    }
    stamp_new(e)
    db.employees[e["id"]] = e
    return success_object(employee_view(e), 201)


@bp.route("/seasons/<sid>/employees", methods=["GET"])
@require_auth(["RecruitingAdmin", "Recruiter"])
def list_employees(sid):
    get_season(sid)
    limit, offset = parse_pagination(request.args)
    items = [e for e in db.employees.values() if e["season_id"] == sid]
    items.sort(key=lambda e: e["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([employee_view(e) for e in page], total, limit, offset)


@bp.route("/employees/<eid>", methods=["GET"])
@require_auth(["RecruitingAdmin", "Recruiter", "Evaluator", "Mentor"])
def get_one_employee(eid):
    e = get_employee(eid)
    # Evaluator/Mentor read own record only
    if g.role in ("Evaluator", "Mentor") and g.user_id != e["id"]:
        from errors import err_forbidden
        raise err_forbidden("Staff role may read only its own employee record")
    return success_object(employee_view(e))


@bp.route("/employees/<eid>/interview-slots", methods=["GET"])
@require_auth(["RecruitingAdmin", "Recruiter", "Evaluator"])
def list_employee_slots(eid):
    e = get_employee(eid)
    if g.role == "Evaluator" and g.user_id != e["id"]:
        from errors import err_forbidden
        raise err_forbidden("Evaluator may read only its own slots")
    limit, offset = parse_pagination(request.args)
    status = request.args.get("status")
    items = [
        s for s in db.interview_slots.values()
        if s["evaluator_id"] == eid
        and (status is None or s["status"] == status)
    ]
    items.sort(key=lambda s: s["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([interview_slot_view(s) for s in page], total, limit, offset)


@bp.route("/employees/<eid>/project-assignments", methods=["GET"])
@require_auth(["RecruitingAdmin", "Recruiter", "Mentor"])
def list_employee_assignments(eid):
    e = get_employee(eid)
    if g.role == "Mentor" and g.user_id != e["id"]:
        from errors import err_forbidden
        raise err_forbidden("Mentor may read only its own assignments")
    limit, offset = parse_pagination(request.args)
    status = request.args.get("status")
    items = [
        a for a in db.project_assignments.values()
        if a["mentor_id"] == eid
        and (status is None or a["status"] == status)
    ]
    items.sort(key=lambda a: a["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([project_assignment_view(a) for a in page], total, limit, offset)


@bp.route("/employees/<eid>/evaluations", methods=["GET"])
@require_auth(["RecruitingAdmin", "Recruiter", "Evaluator"])
def list_employee_evaluations(eid):
    e = get_employee(eid)
    if g.role == "Evaluator" and g.user_id != e["id"]:
        from errors import err_forbidden
        raise err_forbidden("Evaluator may read only its own evaluations")
    limit, offset = parse_pagination(request.args)
    items = [ev for ev in db.evaluations.values() if ev["evaluator_id"] == eid]
    items.sort(key=lambda ev: ev["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([evaluation_view(ev) for ev in page], total, limit, offset)
