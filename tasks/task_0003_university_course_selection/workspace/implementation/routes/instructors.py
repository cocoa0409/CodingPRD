"""Instructor endpoints."""
from flask import Blueprint, request as req
import db
from db import new_id, now_iso
from middleware import require_roles
from response import success_single, success_list
from errors import raise_error, INSTRUCTOR_UNKNOWN
from pagination import parse_page_params, paginate
from routes.semesters import get_semester_or_404

bp = Blueprint("instructors", __name__)


def get_instructor_or_404(semester_id, instructor_id):
    instr = db.instructors.get(instructor_id)
    if not instr or instr.get("semester_id") != semester_id:
        raise_error(INSTRUCTOR_UNKNOWN, f"Instructor {instructor_id} not found in this semester")
    return instr


def instructor_response(instr):
    return {
        "id": instr["id"],
        "semester_id": instr["semester_id"],
        "employee_number": instr["employee_number"],
        "full_name": instr["full_name"],
        "home_department_id": instr["home_department_id"],
        "can_approve_cross_dept": instr.get("can_approve_cross_dept", False),
        "opened_on": instr["opened_on"],
        "modified_on": instr["modified_on"],
        "enrollment_seq": instr.get("enrollment_seq", 1),
    }


@bp.route("/semesters/<semester_id>/instructors", methods=["POST"])
def create_instructor(semester_id):
    require_roles("Registrar")
    get_semester_or_404(semester_id)
    data = req.get_json(force=True)
    now = now_iso()
    instr = {
        "id": new_id(),
        "semester_id": semester_id,
        "employee_number": data.get("employee_number"),
        "full_name": data.get("full_name"),
        "home_department_id": data.get("home_department_id"),
        "can_approve_cross_dept": data.get("can_approve_cross_dept", False),
        "opened_on": now,
        "modified_on": now,
        "enrollment_seq": 1,
    }
    db.instructors[instr["id"]] = instr
    return success_single(instructor_response(instr), 201)


@bp.route("/semesters/<semester_id>/instructors", methods=["GET"])
def list_instructors(semester_id):
    require_roles("Any")
    get_semester_or_404(semester_id)
    page_size, offset = parse_page_params()
    items = [i for i in db.instructors.values() if i.get("semester_id") == semester_id]
    items.sort(key=lambda i: i["opened_on"])
    items = [instructor_response(i) for i in items]
    page_items, total, next_token = paginate(items, page_size, offset)
    return success_list(page_items, page_size, offset, total, next_token)


@bp.route("/semesters/<semester_id>/instructors/<instructor_id>", methods=["GET"])
def get_instructor(semester_id, instructor_id):
    require_roles("Any")
    get_semester_or_404(semester_id)
    instr = get_instructor_or_404(semester_id, instructor_id)
    return success_single(instructor_response(instr))
