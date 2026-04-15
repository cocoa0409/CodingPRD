"""Semester endpoints: CRUD and phase transitions."""
from flask import Blueprint, request as req
import db
from db import new_id, now_iso
from middleware import require_roles
from response import success_single, success_list
from errors import raise_error, SEMESTER_UNKNOWN, SEMESTER_PHASE_INVALID
from pagination import parse_page_params, paginate

bp = Blueprint("semesters", __name__)


def get_semester_or_404(semester_id):
    sem = db.semesters.get(semester_id)
    if not sem:
        raise_error(SEMESTER_UNKNOWN, f"Semester {semester_id} not found")
    return sem


def semester_response(sem):
    return {
        "id": sem["id"],
        "term_label": sem["term_label"],
        "year": sem["year"],
        "registration_opens": sem["registration_opens"],
        "registration_closes": sem["registration_closes"],
        "late_drop_deadline": sem["late_drop_deadline"],
        "phase": sem["phase"],
        "opened_on": sem["opened_on"],
        "modified_on": sem["modified_on"],
        "enrollment_seq": sem.get("enrollment_seq", 1),
    }


@bp.route("/semesters", methods=["POST"])
def create_semester():
    require_roles("Registrar")
    data = req.get_json(force=True)
    now = now_iso()
    sem = {
        "id": new_id(),
        "term_label": data.get("term_label"),
        "year": data.get("year"),
        "registration_opens": data.get("registration_opens"),
        "registration_closes": data.get("registration_closes"),
        "late_drop_deadline": data.get("late_drop_deadline"),
        "phase": "PLANNING",
        "opened_on": now,
        "modified_on": now,
        "enrollment_seq": 1,
    }
    db.semesters[sem["id"]] = sem
    return success_single(semester_response(sem), 201)


@bp.route("/semesters", methods=["GET"])
def list_semesters():
    require_roles("Any")
    page_size, offset = parse_page_params()
    items = sorted(db.semesters.values(), key=lambda s: s["opened_on"])
    items = [semester_response(s) for s in items]
    page_items, total, next_token = paginate(items, page_size, offset)
    return success_list(page_items, page_size, offset, total, next_token)


@bp.route("/semesters/<semester_id>", methods=["GET"])
def get_semester(semester_id):
    require_roles("Any")
    sem = get_semester_or_404(semester_id)
    return success_single(semester_response(sem))


@bp.route("/semesters/<semester_id>/open-enrollment", methods=["POST"])
def open_enrollment(semester_id):
    require_roles("Registrar")
    sem = get_semester_or_404(semester_id)

    if sem["phase"] != "PLANNING":
        raise_error(SEMESTER_PHASE_INVALID, "Semester must be in PLANNING phase to open enrollment")

    # Check that at least one department, course, and section exist
    has_dept = any(d["semester_id"] == semester_id for d in db.departments.values())
    has_course = False
    has_section = False
    if has_dept:
        for c in db.courses.values():
            dept = db.departments.get(c["department_id"])
            if dept and dept["semester_id"] == semester_id:
                has_course = True
                for s in db.sections.values():
                    if s["course_id"] == c["id"]:
                        has_section = True
                        break
                if has_section:
                    break

    if not (has_dept and has_course and has_section):
        raise_error(SEMESTER_PHASE_INVALID,
                    "At least one department, one course, and one section must exist to open enrollment")

    sem["phase"] = "OPEN_ENROLLMENT"
    sem["modified_on"] = now_iso()
    return success_single(semester_response(sem))


@bp.route("/semesters/<semester_id>/close-enrollment", methods=["POST"])
def close_enrollment(semester_id):
    require_roles("Registrar")
    sem = get_semester_or_404(semester_id)

    if sem["phase"] != "OPEN_ENROLLMENT":
        raise_error(SEMESTER_PHASE_INVALID, "Semester must be in OPEN_ENROLLMENT phase to close enrollment")

    now = now_iso()
    sem["phase"] = "CLOSED_ENROLLMENT"
    sem["modified_on"] = now

    # Auto-reject PENDING_APPROVAL and auto-drop WAITLISTED
    for enr in list(db.enrollments.values()):
        section = db.sections.get(enr["section_id"])
        if not section:
            continue
        course = db.courses.get(section["course_id"])
        if not course:
            continue
        dept = db.departments.get(course["department_id"])
        if not dept or dept["semester_id"] != semester_id:
            continue

        if enr["status"] == "PENDING_APPROVAL":
            enr["status"] = "REJECTED"
            enr["approval_note"] = "Registration period closed"
            enr["modified_on"] = now
            # Release credits
            from services.enrollment_service import recompute_student_credits
            recompute_student_credits(enr["student_id"])

        elif enr["status"] == "WAITLISTED":
            enr["status"] = "DROPPED"
            enr["dropped_on"] = now
            enr["approval_note"] = "Registration period closed"
            enr["modified_on"] = now
            section["waitlist_count"] = max(0, section.get("waitlist_count", 0) - 1)
            section["modified_on"] = now

    # Recompute waitlist positions for all sections
    for section in db.sections.values():
        course = db.courses.get(section["course_id"])
        if course:
            dept = db.departments.get(course["department_id"])
            if dept and dept["semester_id"] == semester_id:
                from services.enrollment_service import recompute_waitlist_positions, recompute_section_counts
                recompute_waitlist_positions(section["id"])
                recompute_section_counts(section["id"])

    return success_single(semester_response(sem))


@bp.route("/semesters/<semester_id>/reopen-enrollment", methods=["POST"])
def reopen_enrollment(semester_id):
    require_roles("Registrar")
    sem = get_semester_or_404(semester_id)

    if sem["phase"] != "CLOSED_ENROLLMENT":
        raise_error(SEMESTER_PHASE_INVALID, "Semester must be in CLOSED_ENROLLMENT phase to reopen")

    sem["phase"] = "OPEN_ENROLLMENT"
    sem["modified_on"] = now_iso()
    return success_single(semester_response(sem))


@bp.route("/semesters/<semester_id>/finalize", methods=["POST"])
def finalize_semester(semester_id):
    require_roles("Registrar")
    sem = get_semester_or_404(semester_id)

    if sem["phase"] != "CLOSED_ENROLLMENT":
        raise_error(SEMESTER_PHASE_INVALID, "Semester must be in CLOSED_ENROLLMENT phase to finalize")

    # Check no PENDING_APPROVAL enrollments remain
    for enr in db.enrollments.values():
        if enr["status"] == "PENDING_APPROVAL":
            section = db.sections.get(enr["section_id"])
            if section:
                course = db.courses.get(section["course_id"])
                if course:
                    dept = db.departments.get(course["department_id"])
                    if dept and dept["semester_id"] == semester_id:
                        raise_error(SEMESTER_PHASE_INVALID,
                                    "Cannot finalize: PENDING_APPROVAL enrollments still exist")

    sem["phase"] = "FINALIZED"
    sem["modified_on"] = now_iso()
    return success_single(semester_response(sem))
