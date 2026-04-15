"""Department endpoints."""
from flask import Blueprint, request as req
import db
from db import new_id, now_iso
from middleware import require_roles
from response import success_single, success_list
from errors import raise_error, DEPARTMENT_UNKNOWN
from pagination import parse_page_params, paginate
from routes.semesters import get_semester_or_404

bp = Blueprint("departments", __name__)


def get_department_or_404(semester_id, department_id):
    dept = db.departments.get(department_id)
    if not dept or dept["semester_id"] != semester_id:
        raise_error(DEPARTMENT_UNKNOWN, f"Department {department_id} not found in semester {semester_id}")
    return dept


def department_response(dept):
    return {
        "id": dept["id"],
        "semester_id": dept["semester_id"],
        "dept_code": dept["dept_code"],
        "dept_name": dept["dept_name"],
        "cross_dept_open": dept.get("cross_dept_open", False),
        "opened_on": dept["opened_on"],
        "modified_on": dept["modified_on"],
        "enrollment_seq": dept.get("enrollment_seq", 1),
    }


@bp.route("/semesters/<semester_id>/departments", methods=["POST"])
def create_department(semester_id):
    require_roles("Registrar")
    get_semester_or_404(semester_id)
    data = req.get_json(force=True)
    now = now_iso()
    dept = {
        "id": new_id(),
        "semester_id": semester_id,
        "dept_code": data.get("dept_code"),
        "dept_name": data.get("dept_name"),
        "cross_dept_open": data.get("cross_dept_open", False),
        "opened_on": now,
        "modified_on": now,
        "enrollment_seq": 1,
    }
    db.departments[dept["id"]] = dept
    return success_single(department_response(dept), 201)


@bp.route("/semesters/<semester_id>/departments", methods=["GET"])
def list_departments(semester_id):
    require_roles("Any")
    get_semester_or_404(semester_id)
    page_size, offset = parse_page_params()
    items = [d for d in db.departments.values() if d["semester_id"] == semester_id]
    items.sort(key=lambda d: d["opened_on"])
    items = [department_response(d) for d in items]
    page_items, total, next_token = paginate(items, page_size, offset)
    return success_list(page_items, page_size, offset, total, next_token)


@bp.route("/semesters/<semester_id>/departments/<department_id>", methods=["GET"])
def get_department(semester_id, department_id):
    require_roles("Any")
    get_semester_or_404(semester_id)
    dept = get_department_or_404(semester_id, department_id)
    return success_single(department_response(dept))
