"""Enrollment endpoints: create, list, get, approve, reject, drop, withdraw."""
from flask import Blueprint, request as req
import db
from db import new_id, now_iso
from middleware import require_roles
from response import success_single, success_list
from errors import raise_error, ENROLLMENT_UNKNOWN, REGISTRATION_NOT_OPEN
from pagination import parse_page_params, paginate
from routes.semesters import get_semester_or_404
from routes.departments import get_department_or_404
from routes.courses import get_course_or_404
from routes.sections import get_section_or_404
from services.enrollment_service import (
    create_enrollment, approve_enrollment, reject_enrollment,
    drop_enrollment, withdraw_enrollment
)

bp = Blueprint("enrollments", __name__)

PREFIX = "/semesters/<semester_id>/departments/<department_id>/courses/<course_id>/sections/<section_id>"


def get_enrollment_or_404(section_id, enrollment_id):
    enr = db.enrollments.get(enrollment_id)
    if not enr or enr["section_id"] != section_id:
        raise_error(ENROLLMENT_UNKNOWN, f"Enrollment {enrollment_id} not found")
    return enr


def enrollment_response(enr):
    return {
        "id": enr["id"],
        "section_id": enr["section_id"],
        "student_id": enr["student_id"],
        "status": enr["status"],
        "waitlist_position": enr.get("waitlist_position"),
        "enrolled_on": enr.get("enrolled_on"),
        "dropped_on": enr.get("dropped_on"),
        "approval_note": enr.get("approval_note"),
        "is_cross_dept": enr.get("is_cross_dept", False),
        "enrollment_seq": enr.get("enrollment_seq", 1),
        "opened_on": enr["opened_on"],
        "modified_on": enr["modified_on"],
    }


@bp.route(f"{PREFIX}/enrollments", methods=["POST"])
def create_enrollment_route(semester_id, department_id, course_id, section_id):
    require_roles("Student", "Registrar")
    semester = get_semester_or_404(semester_id)
    get_department_or_404(semester_id, department_id)
    course = get_course_or_404(semester_id, department_id, course_id)
    section = get_section_or_404(semester_id, department_id, course_id, section_id)

    data = req.get_json(force=True)
    student_id = data.get("student_id")
    enrollment_seq = data.get("enrollment_seq")

    enr = create_enrollment(semester, db.departments[department_id], course, section,
                            student_id, enrollment_seq)
    return success_single(enrollment_response(enr), 201)


@bp.route(f"{PREFIX}/enrollments", methods=["GET"])
def list_enrollments(semester_id, department_id, course_id, section_id):
    require_roles("Any")
    get_semester_or_404(semester_id)
    get_department_or_404(semester_id, department_id)
    get_course_or_404(semester_id, department_id, course_id)
    get_section_or_404(semester_id, department_id, course_id, section_id)

    page_size, offset = parse_page_params()
    items = [e for e in db.enrollments.values() if e["section_id"] == section_id]

    # Optional status filter
    status_filter = req.args.get("status")
    if status_filter:
        items = [e for e in items if e["status"] == status_filter]

    items.sort(key=lambda e: e["opened_on"])
    items = [enrollment_response(e) for e in items]
    page_items, total, next_token = paginate(items, page_size, offset)
    return success_list(page_items, page_size, offset, total, next_token)


@bp.route(f"{PREFIX}/enrollments/<enrollment_id>", methods=["GET"])
def get_enrollment(semester_id, department_id, course_id, section_id, enrollment_id):
    require_roles("Any")
    get_semester_or_404(semester_id)
    get_department_or_404(semester_id, department_id)
    get_course_or_404(semester_id, department_id, course_id)
    get_section_or_404(semester_id, department_id, course_id, section_id)
    enr = get_enrollment_or_404(section_id, enrollment_id)
    return success_single(enrollment_response(enr))


@bp.route(f"{PREFIX}/enrollments/<enrollment_id>/approve", methods=["POST"])
def approve_enrollment_route(semester_id, department_id, course_id, section_id, enrollment_id):
    require_roles("Professor")
    semester = get_semester_or_404(semester_id)
    get_department_or_404(semester_id, department_id)
    course = get_course_or_404(semester_id, department_id, course_id)
    section = get_section_or_404(semester_id, department_id, course_id, section_id)
    enr = get_enrollment_or_404(section_id, enrollment_id)

    # Check semester phase
    if semester["phase"] != "OPEN_ENROLLMENT":
        raise_error(REGISTRATION_NOT_OPEN, "Semester is not in OPEN_ENROLLMENT phase")

    student = db.students.get(enr["student_id"])
    data = req.get_json(force=True) if req.data else {}
    approval_note = data.get("approval_note")
    enrollment_seq = data.get("enrollment_seq")

    approve_enrollment(enr, section, course, student, approval_note, enrollment_seq)
    return success_single(enrollment_response(enr))


@bp.route(f"{PREFIX}/enrollments/<enrollment_id>/reject", methods=["POST"])
def reject_enrollment_route(semester_id, department_id, course_id, section_id, enrollment_id):
    require_roles("Professor")
    semester = get_semester_or_404(semester_id)
    get_department_or_404(semester_id, department_id)
    course = get_course_or_404(semester_id, department_id, course_id)
    section = get_section_or_404(semester_id, department_id, course_id, section_id)
    enr = get_enrollment_or_404(section_id, enrollment_id)

    # Check semester phase
    if semester["phase"] != "OPEN_ENROLLMENT":
        raise_error(REGISTRATION_NOT_OPEN, "Semester is not in OPEN_ENROLLMENT phase")

    student = db.students.get(enr["student_id"])
    data = req.get_json(force=True) if req.data else {}
    approval_note = data.get("approval_note")
    enrollment_seq = data.get("enrollment_seq")

    reject_enrollment(enr, section, course, student, approval_note, enrollment_seq)
    return success_single(enrollment_response(enr))


@bp.route(f"{PREFIX}/enrollments/<enrollment_id>/drop", methods=["POST"])
def drop_enrollment_route(semester_id, department_id, course_id, section_id, enrollment_id):
    require_roles("Student", "Registrar")
    semester = get_semester_or_404(semester_id)
    get_department_or_404(semester_id, department_id)
    course = get_course_or_404(semester_id, department_id, course_id)
    section = get_section_or_404(semester_id, department_id, course_id, section_id)
    enr = get_enrollment_or_404(section_id, enrollment_id)

    student = db.students.get(enr["student_id"])
    data = req.get_json(force=True) if req.data else {}
    enrollment_seq = data.get("enrollment_seq")

    drop_enrollment(enr, section, course, student, semester, enrollment_seq)
    return success_single(enrollment_response(enr))


@bp.route(f"{PREFIX}/enrollments/<enrollment_id>/withdraw", methods=["POST"])
def withdraw_enrollment_route(semester_id, department_id, course_id, section_id, enrollment_id):
    require_roles("Registrar")
    semester = get_semester_or_404(semester_id)
    get_department_or_404(semester_id, department_id)
    course = get_course_or_404(semester_id, department_id, course_id)
    section = get_section_or_404(semester_id, department_id, course_id, section_id)
    enr = get_enrollment_or_404(section_id, enrollment_id)

    student = db.students.get(enr["student_id"])
    data = req.get_json(force=True) if req.data else {}
    enrollment_seq = data.get("enrollment_seq")

    withdraw_enrollment(enr, section, course, student, semester, enrollment_seq)
    return success_single(enrollment_response(enr))
