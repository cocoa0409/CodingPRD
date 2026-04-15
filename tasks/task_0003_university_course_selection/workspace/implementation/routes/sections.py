"""Section endpoints."""
from flask import Blueprint, request as req
import db
from db import new_id, now_iso
from middleware import require_roles
from response import success_single, success_list
from errors import raise_error, SECTION_UNKNOWN, COURSE_INACTIVE
from pagination import parse_page_params, paginate
from routes.semesters import get_semester_or_404
from routes.departments import get_department_or_404
from routes.courses import get_course_or_404

bp = Blueprint("sections", __name__)


def get_section_or_404(semester_id, department_id, course_id, section_id):
    section = db.sections.get(section_id)
    if not section or section["course_id"] != course_id:
        raise_error(SECTION_UNKNOWN, f"Section {section_id} not found for course {course_id}")
    return section


def section_response(section):
    return {
        "id": section["id"],
        "course_id": section["course_id"],
        "section_number": section["section_number"],
        "instructor_id": section["instructor_id"],
        "capacity": section["capacity"],
        "waitlist_cap": section.get("waitlist_cap", 10),
        "schedule_days": section["schedule_days"],
        "schedule_start": section["schedule_start"],
        "schedule_end": section["schedule_end"],
        "location": section["location"],
        "seats_enrolled": section.get("seats_enrolled", 0),
        "seats_available": section.get("seats_available", section["capacity"]),
        "waitlist_count": section.get("waitlist_count", 0),
        "requires_approval": section.get("requires_approval", False),
        "enrollment_seq": section.get("enrollment_seq", 1),
        "opened_on": section["opened_on"],
        "modified_on": section["modified_on"],
    }


@bp.route("/semesters/<semester_id>/departments/<department_id>/courses/<course_id>/sections", methods=["POST"])
def create_section(semester_id, department_id, course_id):
    require_roles("Registrar", "Professor")
    get_semester_or_404(semester_id)
    get_department_or_404(semester_id, department_id)
    course = get_course_or_404(semester_id, department_id, course_id)

    if not course.get("is_active", True):
        raise_error(COURSE_INACTIVE, "Cannot create sections for an inactive course")

    data = req.get_json(force=True)
    now = now_iso()
    capacity = data.get("capacity", 30)

    section = {
        "id": new_id(),
        "course_id": course_id,
        "section_number": data.get("section_number"),
        "instructor_id": data.get("instructor_id"),
        "capacity": capacity,
        "waitlist_cap": data.get("waitlist_cap", 10),
        "schedule_days": data.get("schedule_days"),
        "schedule_start": data.get("schedule_start"),
        "schedule_end": data.get("schedule_end"),
        "location": data.get("location"),
        "seats_enrolled": 0,
        "seats_available": capacity,
        "waitlist_count": 0,
        "requires_approval": data.get("requires_approval", False),
        "enrollment_seq": 1,
        "opened_on": now,
        "modified_on": now,
    }
    db.sections[section["id"]] = section
    return success_single(section_response(section), 201)


@bp.route("/semesters/<semester_id>/departments/<department_id>/courses/<course_id>/sections", methods=["GET"])
def list_sections(semester_id, department_id, course_id):
    require_roles("Any")
    get_semester_or_404(semester_id)
    get_department_or_404(semester_id, department_id)
    get_course_or_404(semester_id, department_id, course_id)
    page_size, offset = parse_page_params()

    items = [s for s in db.sections.values() if s["course_id"] == course_id]
    items.sort(key=lambda s: s["opened_on"])
    items = [section_response(s) for s in items]
    page_items, total, next_token = paginate(items, page_size, offset)
    return success_list(page_items, page_size, offset, total, next_token)


@bp.route("/semesters/<semester_id>/departments/<department_id>/courses/<course_id>/sections/<section_id>", methods=["GET"])
def get_section(semester_id, department_id, course_id, section_id):
    require_roles("Any")
    get_semester_or_404(semester_id)
    get_department_or_404(semester_id, department_id)
    get_course_or_404(semester_id, department_id, course_id)
    section = get_section_or_404(semester_id, department_id, course_id, section_id)
    return success_single(section_response(section))


@bp.route("/semesters/<semester_id>/departments/<department_id>/courses/<course_id>/sections/<section_id>", methods=["PATCH"])
def update_section(semester_id, department_id, course_id, section_id):
    require_roles("Registrar", "Professor")
    get_semester_or_404(semester_id)
    get_department_or_404(semester_id, department_id)
    course = get_course_or_404(semester_id, department_id, course_id)
    section = get_section_or_404(semester_id, department_id, course_id, section_id)
    data = req.get_json(force=True)

    # OCC check
    if "enrollment_seq" in data:
        from services.enrollment_service import check_enrollment_seq
        check_enrollment_seq(section, data["enrollment_seq"])

    old_capacity = section["capacity"]
    schedule_changed = False

    if "capacity" in data:
        section["capacity"] = data["capacity"]
        section["seats_available"] = section["capacity"] - section["seats_enrolled"]

    if "waitlist_cap" in data:
        section["waitlist_cap"] = data["waitlist_cap"]

    for field in ["schedule_days", "schedule_start", "schedule_end"]:
        if field in data:
            if data[field] != section.get(field):
                schedule_changed = True
            section[field] = data[field]

    if "location" in data:
        section["location"] = data["location"]
    if "requires_approval" in data:
        section["requires_approval"] = data["requires_approval"]

    section["modified_on"] = now_iso()

    # If capacity increased, trigger waitlist promotion cascade
    new_capacity = section["capacity"]
    if new_capacity > old_capacity:
        new_seats = new_capacity - old_capacity
        from services.enrollment_service import try_waitlist_promotion
        for _ in range(new_seats):
            if section["seats_available"] > 0:
                try_waitlist_promotion(section, course, "capacity increase")

    # If schedule changed, detect conflicts for enrolled students
    if schedule_changed:
        from services.schedule import check_schedule_conflict
        for enr in db.enrollments.values():
            if enr["section_id"] == section_id and enr["status"] == "ENROLLED":
                conflicts = check_schedule_conflict(enr["student_id"], section)
                for conflict in conflicts:
                    conflict_record = {
                        "id": new_id(),
                        "student_id": enr["student_id"],
                        "section_a_id": conflict["section_a_id"],
                        "section_b_id": conflict["section_b_id"],
                        "overlap_days": conflict["overlap_days"],
                        "overlap_minutes": conflict["overlap_minutes"],
                        "detected_on": now_iso()
                    }
                    db.schedule_conflicts[conflict_record["id"]] = conflict_record

    return success_single(section_response(section))
