"""Course + Student routes."""

from flask import Blueprint

import db
from errors import ApiError
from middleware import get_auth, require_owner, require_roles
from response import success_object
from util import as_bool, as_number, as_str, json_body, make_resource, optional, require

bp = Blueprint("courses_students", __name__)


# ---------------------------------------------------------------------------
# POST /courses
# ---------------------------------------------------------------------------


@bp.route("/courses", methods=["POST"])
def create_course():
    _, role = get_auth()
    require_roles(role, ("RegistrarStaff",))
    body = json_body()

    course_code = as_str(require(body, "course_code"), "course_code")
    title = as_str(require(body, "title"), "title")
    credits = as_number(require(body, "credits"), "credits")

    for c in db.courses.values():
        if c["course_code"] == course_code:
            raise ApiError(
                "ERR_UNIQUE_CONSTRAINT_VIOLATION", "course_code already exists."
            )

    course = make_resource(
        {"course_code": course_code, "title": title, "credits": credits}
    )
    db.courses[course["id"]] = course
    return success_object(course, 201)


# ---------------------------------------------------------------------------
# POST /students
# ---------------------------------------------------------------------------


@bp.route("/students", methods=["POST"])
def create_student():
    _, role = get_auth()
    require_roles(role, ("RegistrarStaff",))
    body = json_body()

    student_number = as_str(require(body, "student_number"), "student_number")
    legal_name = as_str(require(body, "legal_name"), "legal_name")
    financial_hold = optional(body, "financial_hold", False)
    if financial_hold is None:
        financial_hold = False
    financial_hold = as_bool(financial_hold, "financial_hold")

    for s in db.students.values():
        if s["student_number"] == student_number:
            raise ApiError(
                "ERR_UNIQUE_CONSTRAINT_VIOLATION", "student_number already exists."
            )

    student = make_resource(
        {
            "student_number": student_number,
            "legal_name": legal_name,
            "financial_hold": financial_hold,
            "status": "ACTIVE",
            "total_earned_credits": 0,
            "institutional_earned_credits": 0,
            "institutional_gpa": 0.0,
            "cumulative_gpa": 0.0,
        }
    )
    db.students[student["id"]] = student
    return success_object(student, 201)


# ---------------------------------------------------------------------------
# GET /students/{id}
# ---------------------------------------------------------------------------


@bp.route("/students/<student_id>", methods=["GET"])
def get_student(student_id):
    user_id, role = get_auth()
    require_roles(role, ("RegistrarStaff", "Advisor", "Student"))
    student = db.students.get(student_id)
    if student is None:
        raise ApiError("ERR_STUDENT_NOT_FOUND", "Student not found.")
    if role == "Student":
        require_owner(user_id, student["id"])
    return success_object(student)
