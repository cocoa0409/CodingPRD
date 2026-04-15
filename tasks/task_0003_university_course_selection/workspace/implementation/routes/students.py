"""Student endpoints."""
from flask import Blueprint, request as req
import db
from db import new_id, now_iso
from middleware import require_roles
from response import success_single, success_list
from errors import raise_error, STUDENT_UNKNOWN
from pagination import parse_page_params, paginate
from routes.semesters import get_semester_or_404
from services.enrollment_service import get_effective_max_credits

bp = Blueprint("students", __name__)


def get_student_or_404(semester_id, student_id):
    student = db.students.get(student_id)
    if not student or student.get("semester_id") != semester_id:
        raise_error(STUDENT_UNKNOWN, f"Student {student_id} not found in this semester")
    return student


def student_response(student):
    effective_max = get_effective_max_credits(student)
    credits_enrolled = student.get("credits_enrolled", 0)
    return {
        "id": student["id"],
        "semester_id": student["semester_id"],
        "student_number": student["student_number"],
        "full_name": student["full_name"],
        "major_department_id": student["major_department_id"],
        "academic_standing": student.get("academic_standing", "GOOD"),
        "cumulative_gpa": student.get("cumulative_gpa", 0.0),
        "max_credits": student.get("max_credits", 18),
        "credits_enrolled": credits_enrolled,
        "credits_available": effective_max - credits_enrolled,
        "completed_course_ids": student.get("completed_course_ids", []),
        "opened_on": student["opened_on"],
        "modified_on": student["modified_on"],
        "enrollment_seq": student.get("enrollment_seq", 1),
    }


@bp.route("/semesters/<semester_id>/students", methods=["POST"])
def create_student(semester_id):
    require_roles("Registrar")
    get_semester_or_404(semester_id)
    data = req.get_json(force=True)
    now = now_iso()
    max_credits = data.get("max_credits", 18)
    student = {
        "id": new_id(),
        "semester_id": semester_id,
        "student_number": data.get("student_number"),
        "full_name": data.get("full_name"),
        "major_department_id": data.get("major_department_id"),
        "academic_standing": data.get("academic_standing", "GOOD"),
        "cumulative_gpa": data.get("cumulative_gpa", 0.0),
        "max_credits": max_credits,
        "credits_enrolled": 0,
        "credits_available": max_credits,
        "completed_course_ids": data.get("completed_course_ids", []),
        "opened_on": now,
        "modified_on": now,
        "enrollment_seq": 1,
    }
    db.students[student["id"]] = student
    return success_single(student_response(student), 201)


@bp.route("/semesters/<semester_id>/students", methods=["GET"])
def list_students(semester_id):
    require_roles("Any")
    get_semester_or_404(semester_id)
    page_size, offset = parse_page_params()
    items = [s for s in db.students.values() if s.get("semester_id") == semester_id]

    # Optional academic_standing filter
    standing_filter = req.args.get("academic_standing")
    if standing_filter:
        items = [s for s in items if s.get("academic_standing") == standing_filter]

    items.sort(key=lambda s: s["opened_on"])
    items = [student_response(s) for s in items]
    page_items, total, next_token = paginate(items, page_size, offset)
    return success_list(page_items, page_size, offset, total, next_token)


@bp.route("/semesters/<semester_id>/students/<student_id>", methods=["GET"])
def get_student(semester_id, student_id):
    require_roles("Any")
    get_semester_or_404(semester_id)
    student = get_student_or_404(semester_id, student_id)
    return success_single(student_response(student))


@bp.route("/semesters/<semester_id>/students/<student_id>", methods=["PATCH"])
def update_student(semester_id, student_id):
    require_roles("Registrar")
    get_semester_or_404(semester_id)
    student = get_student_or_404(semester_id, student_id)
    data = req.get_json(force=True)

    if "max_credits" in data:
        student["max_credits"] = data["max_credits"]
    if "completed_course_ids" in data:
        student["completed_course_ids"] = data["completed_course_ids"]
    if "academic_standing" in data:
        student["academic_standing"] = data["academic_standing"]

    # Recompute credits
    from services.enrollment_service import recompute_student_credits
    recompute_student_credits(student_id)

    student["modified_on"] = now_iso()
    return success_single(student_response(student))


@bp.route("/semesters/<semester_id>/students/<student_id>/schedule", methods=["GET"])
def get_student_schedule(semester_id, student_id):
    require_roles("Student", "Registrar", "Professor")
    get_semester_or_404(semester_id)
    student = get_student_or_404(semester_id, student_id)

    # Get all sections where the student is ENROLLED
    from routes.sections import section_response
    enrolled_sections = []
    for enr in db.enrollments.values():
        if enr["student_id"] == student_id and enr["status"] == "ENROLLED":
            section = db.sections.get(enr["section_id"])
            if section:
                enrolled_sections.append(section_response(section))

    enrolled_sections.sort(key=lambda s: s.get("opened_on", ""))

    page_size = len(enrolled_sections) if enrolled_sections else 20
    return success_list(enrolled_sections, page_size, 0, len(enrolled_sections), None)
