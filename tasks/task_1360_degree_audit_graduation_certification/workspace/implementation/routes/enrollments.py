"""Enrollment routes: create, list, get, post-grade, grade-changes."""

from flask import Blueprint, request

import db
from errors import ApiError
from middleware import get_auth, parse_pagination, require_owner, require_roles
from response import success_list, success_object
from services.academic import ALL_GRADES, apply_grade_to_enrollment
from services.cascade import recompute_student_cascade
from util import (
    as_bool,
    as_enum,
    as_str,
    json_body,
    make_resource,
    optional,
    paginate,
    require,
    touch,
)

bp = Blueprint("enrollments", __name__)


def _get_enrollment_or_404(enrollment_id):
    e = db.enrollments.get(enrollment_id)
    if e is None:
        raise ApiError("ERR_ENROLLMENT_NOT_FOUND", "Enrollment not found.")
    return e


# ---------------------------------------------------------------------------
# POST /students/{id}/enrollments
# ---------------------------------------------------------------------------


@bp.route("/students/<student_id>/enrollments", methods=["POST"])
def create_enrollment(student_id):
    _, role = get_auth()
    require_roles(role, ("RegistrarStaff",))
    student = db.students.get(student_id)
    if student is None:
        raise ApiError("ERR_STUDENT_NOT_FOUND", "Student not found.")
    body = json_body()

    course_id = require(body, "course_id")
    course = db.courses.get(course_id)
    if course is None:
        raise ApiError("ERR_COURSE_NOT_FOUND", "Course not found.")
    term = as_str(require(body, "term"), "term")
    is_transfer = optional(body, "is_transfer", False)
    if is_transfer is None:
        is_transfer = False
    is_transfer = as_bool(is_transfer, "is_transfer")
    grade = optional(body, "grade", None)
    if grade is not None:
        grade = as_enum(grade, "grade", ALL_GRADES)

    # Duplicate (student, course, term) with IN_PROGRESS or COMPLETED sibling
    for e in db.enrollments.values():
        if (
            e["student_id"] == student["id"]
            and e["course_id"] == course["id"]
            and e["term"] == term
            and e["status"] in ("IN_PROGRESS", "COMPLETED")
        ):
            raise ApiError(
                "ERR_DUPLICATE_ENROLLMENT",
                "An enrollment for (student, course, term) already exists.",
            )

    enrollment = make_resource(
        {
            "student_id": student["id"],
            "course_id": course["id"],
            "term": term,
            "is_transfer": is_transfer,
            "grade": None,
            "status": "IN_PROGRESS",
            "credits_attempted": course["credits"],
            "credits_earned": 0,
            "grade_points": 0,
        }
    )
    db.enrollments[enrollment["id"]] = enrollment

    if grade is not None:
        apply_grade_to_enrollment(enrollment, grade)
        touch(enrollment)
        recompute_student_cascade(student["id"])

    return success_object(enrollment, 201)


# ---------------------------------------------------------------------------
# GET /enrollments  (filters: student_id, course_id, status, term)
# ---------------------------------------------------------------------------


@bp.route("/enrollments", methods=["GET"])
def list_enrollments():
    user_id, role = get_auth()
    require_roles(role, ("RegistrarStaff", "Advisor", "Student"))
    limit, offset = parse_pagination()

    items = list(db.enrollments.values())
    if role == "Student":
        items = [e for e in items if e["student_id"] == user_id]
    student_id = request.args.get("student_id")
    course_id = request.args.get("course_id")
    status = request.args.get("status")
    term = request.args.get("term")
    if student_id:
        items = [e for e in items if e["student_id"] == student_id]
    if course_id:
        items = [e for e in items if e["course_id"] == course_id]
    if status:
        items = [e for e in items if e["status"] == status]
    if term:
        items = [e for e in items if e["term"] == term]
    page, total = paginate(items, limit, offset)
    return success_list(page, limit, offset, total)


# ---------------------------------------------------------------------------
# GET /enrollments/{id}
# ---------------------------------------------------------------------------


@bp.route("/enrollments/<enrollment_id>", methods=["GET"])
def get_enrollment(enrollment_id):
    user_id, role = get_auth()
    require_roles(role, ("RegistrarStaff", "Advisor", "Student"))
    e = _get_enrollment_or_404(enrollment_id)
    if role == "Student":
        require_owner(user_id, e["student_id"])
    return success_object(e)


# ---------------------------------------------------------------------------
# POST /enrollments/{id}/post-grade
# ---------------------------------------------------------------------------


@bp.route("/enrollments/<enrollment_id>/post-grade", methods=["POST"])
def post_grade(enrollment_id):
    _, role = get_auth()
    require_roles(role, ("RegistrarStaff",))
    e = _get_enrollment_or_404(enrollment_id)
    body = json_body()
    grade = as_enum(require(body, "grade"), "grade", ALL_GRADES)

    if e["status"] != "IN_PROGRESS":
        raise ApiError(
            "ERR_ENROLLMENT_INVALID_STATE",
            "post-grade requires an IN_PROGRESS enrollment.",
        )

    apply_grade_to_enrollment(e, grade)
    touch(e)
    recompute_student_cascade(e["student_id"])
    return success_object(e)


# ---------------------------------------------------------------------------
# POST /enrollments/{id}/grade-changes
# ---------------------------------------------------------------------------


@bp.route("/enrollments/<enrollment_id>/grade-changes", methods=["POST"])
def grade_change(enrollment_id):
    _, role = get_auth()
    require_roles(role, ("RegistrarStaff",))
    e = _get_enrollment_or_404(enrollment_id)
    body = json_body()
    new_grade = as_enum(require(body, "new_grade"), "new_grade", ALL_GRADES)
    require(body, "reason")  # required field; value not persisted on entity

    if e["status"] not in ("COMPLETED", "WITHDRAWN"):
        raise ApiError(
            "ERR_ENROLLMENT_INVALID_STATE",
            "grade-changes requires a COMPLETED or WITHDRAWN enrollment.",
        )

    apply_grade_to_enrollment(e, new_grade)
    touch(e)
    recompute_student_cascade(e["student_id"])
    return success_object(e)
