"""The master schedule: sections, and the add/drop of enrollments."""
from flask import Blueprint

import auth
import calc
import cascade
import envelope
import serial
import shape
import store
from errors import ApiError
from routes_reads import fetch

bp = Blueprint("roster", __name__)

LIVE = ("PENDING_ADD", "ACTIVE", "PENDING_DROP")


def _drop_row(enrollment, drop_date, today):
    """Shared by an explicit drop and by section cancellation."""
    enrollment["drop_effective_date"] = store.fmt_date(drop_date)
    enrollment["roster_status"] = "DROPPED" if drop_date <= today else "PENDING_DROP"
    store.touch(enrollment)
    return enrollment["roster_status"] == "DROPPED"


# ----------------------------------------------------------------- sections
@bp.post("/rostering/sections")
def create_section():
    auth.require(auth.ROSTER_OPERATOR)
    body = shape.body()
    school_id = shape.req_id(body, "school_id")
    term_id = shape.req_id(body, "term_id")
    teacher_id = shape.opt_id(body, "primary_teacher_id")
    sis_section_id = shape.req_str(body, "sis_section_id", 1, 64)
    course_code = shape.req_str(body, "course_code", 1, 32)
    subject = shape.req_enum(body, "subject", shape.SUBJECTS)
    period_index = shape.req_int(body, "period_index", 1, 8)
    meeting_days = shape.req_enum_array(body, "meeting_days", shape.MEETING_DAYS)
    max_seats = shape.req_int(body, "max_seats", 1, 60)

    school = fetch(store.schools, school_id, "ERR_SCHOOL_NOT_FOUND")
    term = fetch(store.terms, term_id, "ERR_TERM_NOT_FOUND")
    teacher = None
    if teacher_id is not None:
        teacher = fetch(store.teachers, teacher_id, "ERR_TEACHER_NOT_FOUND")

    if school.get("status") != "ACTIVE":
        raise ApiError("ERR_SCHOOL_CLOSED", "The building is CLOSED.")
    if term.get("state") != "ACTIVE":
        raise ApiError("ERR_TERM_NOT_ACTIVE", "The term is not ACTIVE.")
    if teacher is not None and teacher.get("employment_status") != "ACTIVE":
        raise ApiError("ERR_TEACHER_SEPARATED", "The teacher is SEPARATED.")
    if teacher is not None and calc.teacher_period_conflict(
            teacher_id, term_id, period_index, meeting_days):
        raise ApiError("ERR_TEACHER_PERIOD_CONFLICT",
                       "The teacher already meets within one period of this one.")

    record = {
        "school_id": school_id,
        "term_id": term_id,
        "primary_teacher_id": teacher_id,
        "sis_section_id": sis_section_id,
        "course_code": course_code,
        "subject": subject,
        "period_index": period_index,
        "meeting_days": list(meeting_days),
        "max_seats": max_seats,
        "status": "ACTIVE",
        "roster_health": "OK" if teacher_id is not None else "UNMATCHED_TEACHER",
        "active_enrollment_count": 0,
    }
    store.stamp_new(record)
    store.sections[record["id"]] = record
    return envelope.created(serial.section(record))


@bp.patch("/rostering/sections/<section_id>")
def amend_section(section_id):
    auth.require(auth.ROSTER_OPERATOR)
    section = fetch(store.sections, section_id, "ERR_SECTION_NOT_FOUND")
    body = shape.body()
    max_seats = shape.opt_int(body, "max_seats", None, 1, 60)
    teacher_id = shape.opt_id(body, "primary_teacher_id")
    status = shape.opt_enum(body, "status", ["ACTIVE", "CANCELLED"])
    if shape.present(body, "status") and body["status"] == "ARCHIVED":
        shape.bad("ARCHIVED is written only by summer rollover.")

    teacher = None
    if teacher_id is not None:
        teacher = fetch(store.teachers, teacher_id, "ERR_TEACHER_NOT_FOUND")
        if teacher.get("employment_status") != "ACTIVE":
            raise ApiError("ERR_TEACHER_SEPARATED", "The teacher is SEPARATED.")

    if max_seats is not None:
        section["max_seats"] = max_seats
    if teacher_id is not None:
        section["primary_teacher_id"] = teacher_id
        section["roster_health"] = "OK"
    cancelled = status == "CANCELLED" and section.get("status") != "CANCELLED"
    if status is not None:
        section["status"] = status
    store.touch(section)

    if cancelled:
        today = store.clock_date()
        students = []
        for enrollment in store.sorted_records(store.enrollments):
            if enrollment.get("section_id") != section_id:
                continue
            if enrollment.get("roster_status") == "DROPPED":
                continue
            enrollment["roster_status"] = "DROPPED"
            if not enrollment.get("drop_effective_date"):
                enrollment["drop_effective_date"] = store.fmt_date(today)
            store.touch(enrollment)
            student = store.students.get(enrollment.get("student_id"))
            if student is not None and student not in students:
                students.append(student)
        cascade.recompute_section_count(section)
        for student in students:
            cascade.recompute_student_count(student)
            cascade.release_student_seats(student, today)

    return envelope.ok(serial.section(section))


# -------------------------------------------------------------- enrollments
@bp.post("/rostering/enrollments")
def create_enrollment():
    auth.require(auth.ROSTER_OPERATOR)
    body = shape.body()
    section_id = shape.req_id(body, "section_id")
    student_id = shape.req_id(body, "student_id")
    requested = shape.req_date(body, "requested_effective_date")
    source = shape.opt_enum(body, "source", shape.ENROLLMENT_SOURCES, "MANUAL")

    section = fetch(store.sections, section_id, "ERR_SECTION_NOT_FOUND")
    student = fetch(store.students, student_id, "ERR_STUDENT_NOT_FOUND")
    term = store.terms.get(section.get("term_id"))

    if term is None or term.get("state") != "ACTIVE":
        raise ApiError("ERR_TERM_NOT_ACTIVE", "The section's term is not ACTIVE.")
    if student.get("enrollment_state") != "ENROLLED":
        raise ApiError("ERR_STUDENT_NOT_ENROLLED", "The student is not ENROLLED.")
    start = calc.as_date(term["start_date"])
    end = calc.as_date(term["end_date"])
    if not (start <= requested <= end):
        raise ApiError("ERR_EFFECTIVE_DATE_OUT_OF_TERM",
                       "requested_effective_date is outside the term window.")
    if calc.student_schedule_conflict(student_id, section, requested):
        raise ApiError("ERR_STUDENT_SCHEDULE_CONFLICT",
                       "The student already meets in this period on a shared day.")
    if student.get("school_id") != section.get("school_id"):
        raise ApiError("ERR_SCHOOL_MISMATCH",
                       "The student and the section are in different buildings.")
    for other in store.enrollments.values():
        if (other.get("section_id") == section_id
                and other.get("student_id") == student_id
                and other.get("roster_status") != "DROPPED"):
            raise ApiError("ERR_DUPLICATE_ENROLLMENT",
                           "The student already holds this section.")
    if (section.get("active_enrollment_count") or 0) >= (section.get("max_seats") or 0):
        raise ApiError("ERR_SECTION_AT_CAPACITY", "The section is full.")

    today = store.clock_date()
    record = {
        "section_id": section_id,
        "student_id": student_id,
        "requested_effective_date": store.fmt_date(requested),
        "effective_date": store.fmt_date(requested),
        "drop_effective_date": None,
        "roster_status": "PENDING_ADD",
        "add_drop_class": ("IN_WINDOW"
                           if requested <= calc.as_date(term["add_drop_cutoff_date"])
                           else "LATE_ADD"),
        "source": source,
    }
    if requested <= today:
        record["roster_status"] = "ACTIVE"
    store.stamp_new(record)
    store.enrollments[record["id"]] = record
    # PENDING_ADD already occupies a physical chair (PRD 2.9), so both counters
    # move whether or not the row advanced to ACTIVE in this same request.
    cascade.recompute_section_count(section)
    cascade.recompute_student_count(student)
    return envelope.created(serial.enrollment(record))


@bp.post("/rostering/enrollments/<enrollment_id>/drop")
def drop_enrollment(enrollment_id):
    auth.require(auth.ROSTER_OPERATOR)
    enrollment = fetch(store.enrollments, enrollment_id, "ERR_ENROLLMENT_NOT_FOUND")
    body = shape.body()
    drop_date = shape.req_date(body, "drop_effective_date")
    section = store.sections.get(enrollment.get("section_id"))
    term = store.terms.get(section.get("term_id")) if section else None

    if term is None or term.get("state") != "ACTIVE":
        raise ApiError("ERR_TERM_NOT_ACTIVE", "The section's term is not ACTIVE.")
    if enrollment.get("roster_status") not in ("PENDING_ADD", "ACTIVE"):
        raise ApiError("ERR_ENROLLMENT_NOT_DROPPABLE",
                       "Only a PENDING_ADD or ACTIVE row can be dropped.")
    basis = enrollment.get("effective_date") or enrollment.get("requested_effective_date")
    if drop_date < calc.as_date(basis) or drop_date > calc.as_date(term["end_date"]):
        raise ApiError("ERR_DROP_BEFORE_ADD",
                       "drop_effective_date must fall between the add and the term end.")

    today = store.clock_date()
    student = store.students.get(enrollment.get("student_id"))
    became_dropped = _drop_row(enrollment, drop_date, today)
    # A PENDING_DROP row leaves the section's active_enrollment_count (which
    # counts only PENDING_ADD and ACTIVE rows) while it stays inside the
    # student's own count, so both figures are recomputed either way.
    cascade.recompute_section_count(section)
    cascade.recompute_student_count(student)
    if became_dropped:
        cascade.release_student_seats(student, drop_date)
    return envelope.ok(serial.enrollment(enrollment))
