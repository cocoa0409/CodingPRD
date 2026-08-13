"""Students: register, list, detail, district iep_status write-back."""
from flask import Blueprint, request

from db import db, create_record, touch
from errors import ApiError, ERR_INVALID_REQUEST
from middleware import (body, opt_enum, parse_bool_filter, req_int, req_str,
                        require_roles)
from response import success
from routes import list_response
from services import (IEP_STATUSES, get_school, get_student, has_active_plan,
                      posture_gate, school_of_student, student_out)
from util import parse_dt

bp = Blueprint("students", __name__)


@bp.post("/students")
@require_roles("Section504Coordinator", "SchoolPrincipal")
def create_student():
    d = body()
    school = get_school(req_str(d, "school_id"))
    posture_gate(school)
    grade = req_int(d, "grade_level")
    if grade < 0 or grade > 12:
        raise ApiError(ERR_INVALID_REQUEST[0], ERR_INVALID_REQUEST[1],
                       "Field 'grade_level': must be an integer from 0 through 12")
    rec = create_record(db.students, {
        "school_id": school["id"],
        "student_external_ref": req_str(d, "student_external_ref"),
        "full_name": req_str(d, "full_name"),
        "date_of_birth": parse_dt(req_str(d, "date_of_birth"), "date_of_birth"),
        "grade_level": grade,
        "section_504_status": "NONE",
        "iep_status": "NONE",
        "has_active_504_plan": False,
    })
    return success(student_out(rec), 201)


@bp.get("/students")
@require_roles("District504Director", "Section504Coordinator", "SchoolPrincipal", "Teacher")
def list_students():
    items = list(db.students.values())
    school_id = request.args.get("school_id")
    s504 = request.args.get("section_504_status")
    iep = request.args.get("iep_status")
    has_plan = parse_bool_filter("has_active_504_plan")
    if school_id is not None:
        items = [s for s in items if s["school_id"] == school_id]
    if s504 is not None:
        items = [s for s in items if s["section_504_status"] == s504]
    if iep is not None:
        items = [s for s in items if s["iep_status"] == iep]
    if has_plan is not None:
        items = [s for s in items if has_active_plan(s["id"]) == has_plan]
    return list_response(items, student_out)


@bp.get("/students/<studentId>")
@require_roles("District504Director", "Section504Coordinator", "SchoolPrincipal", "Teacher", "Parent")
def get_student_detail(studentId):
    return success(student_out(get_student(studentId)), 200)


@bp.patch("/students/<studentId>")
@require_roles("District504Director")
def update_student(studentId):
    stu = get_student(studentId)
    posture_gate(school_of_student(stu))
    d = body()
    new_iep = opt_enum(d, "iep_status", IEP_STATUSES, None)
    if new_iep is not None and new_iep != stu["iep_status"]:
        # No automatic cascade when IEP_ACTIVE arrives while a plan is ACTIVE.
        stu["iep_status"] = new_iep
    touch(stu)
    return success(student_out(stu), 200)
