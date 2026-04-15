"""Diagnostic endpoints: schedule conflicts and waitlist promotions."""
from flask import Blueprint, request as req
import db
from middleware import require_roles
from response import success_list
from pagination import parse_page_params, paginate
from routes.semesters import get_semester_or_404

bp = Blueprint("diagnostics", __name__)


def conflict_response(conflict):
    return {
        "id": conflict["id"],
        "student_id": conflict["student_id"],
        "section_a_id": conflict["section_a_id"],
        "section_b_id": conflict["section_b_id"],
        "overlap_days": conflict["overlap_days"],
        "overlap_minutes": conflict["overlap_minutes"],
        "detected_on": conflict["detected_on"],
    }


def promotion_response(promo):
    return {
        "id": promo["id"],
        "enrollment_id": promo["enrollment_id"],
        "section_id": promo["section_id"],
        "previous_position": promo["previous_position"],
        "trigger_event": promo["trigger_event"],
        "promoted_on": promo["promoted_on"],
    }


@bp.route("/semesters/<semester_id>/schedule-conflicts", methods=["GET"])
def list_schedule_conflicts(semester_id):
    require_roles("Registrar")
    get_semester_or_404(semester_id)
    page_size, offset = parse_page_params()

    # Filter conflicts for this semester
    items = []
    for conflict in db.schedule_conflicts.values():
        # Check if either section belongs to this semester
        section_a = db.sections.get(conflict["section_a_id"])
        section_b = db.sections.get(conflict["section_b_id"])
        if section_a or section_b:
            # Verify the section belongs to a course in a department in this semester
            for s in [section_a, section_b]:
                if s:
                    course = db.courses.get(s["course_id"])
                    if course:
                        dept = db.departments.get(course["department_id"])
                        if dept and dept["semester_id"] == semester_id:
                            items.append(conflict)
                            break

    # Optional student_id filter
    student_filter = req.args.get("student_id")
    if student_filter:
        items = [c for c in items if c["student_id"] == student_filter]

    items.sort(key=lambda c: c["detected_on"])
    items = [conflict_response(c) for c in items]
    page_items, total, next_token = paginate(items, page_size, offset)
    return success_list(page_items, page_size, offset, total, next_token)


@bp.route("/semesters/<semester_id>/waitlist-promotions", methods=["GET"])
def list_waitlist_promotions(semester_id):
    require_roles("Registrar")
    get_semester_or_404(semester_id)
    page_size, offset = parse_page_params()

    # Filter promotions for this semester
    items = []
    for promo in db.waitlist_promotions.values():
        section = db.sections.get(promo["section_id"])
        if section:
            course = db.courses.get(section["course_id"])
            if course:
                dept = db.departments.get(course["department_id"])
                if dept and dept["semester_id"] == semester_id:
                    items.append(promo)

    # Optional section_id filter
    section_filter = req.args.get("section_id")
    if section_filter:
        items = [p for p in items if p["section_id"] == section_filter]

    items.sort(key=lambda p: p["promoted_on"])
    items = [promotion_response(p) for p in items]
    page_items, total, next_token = paginate(items, page_size, offset)
    return success_list(page_items, page_size, offset, total, next_token)
