"""Class sections, enrollments, the attendance hour ledger and test events."""

from decimal import Decimal

from flask import Blueprint, request

import calc
import cascades
from core import (
    auth,
    body,
    by_created,
    clock,
    created,
    deny_scope,
    find_entry,
    find_enrollment,
    find_section,
    find_student,
    find_test_event,
    fmt_clock,
    hours_out,
    new_record,
    ok,
    opt_fk,
    pagination,
    paginate,
    parse_date,
    pub,
    q2,
    recompute_student_hours,
    recount_section_seats,
    req_date,
    req_dec,
    req_dt,
    req_enum,
    req_fk,
    req_int,
    req_str,
    store,
    touch,
)
from errors import ApiError

bp = Blueprint("instruction", __name__)

SECTION_STATUSES = ("PLANNED", "OPEN", "IN_SESSION", "CLOSED")
SECTION_TRANSITIONS = {
    "PLANNED": ("OPEN",),
    "OPEN": ("IN_SESSION", "CLOSED"),
    "IN_SESSION": ("CLOSED",),
    "CLOSED": (),
}


# --------------------------------------------------------------------------
# class sections
# --------------------------------------------------------------------------

@bp.post("/class-sections")
def create_section():
    auth("ProgramCoordinator")
    data = body()
    program_track = req_enum(data, "program_track", calc.PROGRAM_TRACKS)
    title = req_str(data, "title")
    instructor_user_id = req_str(data, "instructor_user_id")
    min_level = req_int(data, "min_efl_level", minimum=1, maximum=6)
    max_level = req_int(data, "max_efl_level", minimum=1, maximum=6)
    if max_level < min_level:
        raise ApiError("ERR_INVALID_REQUEST")
    seats_total = req_int(data, "seats_total", minimum=1, maximum=60)
    weekly_hours = req_dec(data, "weekly_hours", exclusive_min=0, maximum=40)

    section = new_record(store.sections, {
        "program_track": program_track,
        "title": title,
        "instructor_user_id": instructor_user_id,
        "min_efl_level": min_level,
        "max_efl_level": max_level,
        "seats_total": seats_total,
        "seats_taken": 0,
        "seats_available": seats_total,
        "weekly_hours": hours_out(weekly_hours),
        "status": "PLANNED",
    })
    return created(pub(section))


@bp.post("/class-sections/<section_id>/status-transition")
def section_status_transition(section_id):
    auth("ProgramCoordinator")
    section = find_section(section_id)
    data = body()
    target = req_enum(data, "target_status", SECTION_STATUSES)
    if target not in SECTION_TRANSITIONS[section["status"]]:
        raise ApiError("ERR_SECTION_TRANSITION_NOT_ALLOWED")
    if target == "CLOSED":
        cascades.close_section(section)
    else:
        section["status"] = target
        touch(section)
    return ok(pub(section))


@bp.get("/class-sections/<section_id>")
def read_section(section_id):
    auth("ProgramCoordinator", "StateAuthority", "Instructor", "Registrar")
    return ok(pub(find_section(section_id)))


@bp.get("/class-sections")
def list_sections():
    auth("ProgramCoordinator", "StateAuthority", "Instructor", "Registrar")
    limit, offset = pagination()
    rows = list(store.sections.values())
    for key in ("program_track", "status"):
        wanted = request.args.get(key)
        if wanted is not None:
            rows = [r for r in rows if r[key] == wanted]
    return paginate(by_created(rows), limit, offset)


# --------------------------------------------------------------------------
# enrollments
# --------------------------------------------------------------------------

@bp.post("/enrollments")
def create_enrollment():
    auth("ProgramCoordinator")
    data = body()
    student_id = req_fk(data, "student_id")
    section_id = req_fk(data, "class_section_id")
    student = find_student(student_id)
    section = find_section(section_id)

    if student["placement_efl_level"] is None:
        raise ApiError("ERR_PLACEMENT_TEST_MISSING")
    if section["status"] not in ("OPEN", "IN_SESSION"):
        raise ApiError("ERR_SECTION_NOT_ACCEPTING_ENROLLMENT")
    for enrollment in store.enrollments.values():
        if enrollment["student_id"] != student["id"] or enrollment["status"] != "ACTIVE":
            continue
        other = store.sections.get(enrollment["class_section_id"])
        if other is not None and other["program_track"] == section["program_track"]:
            raise ApiError("ERR_DUPLICATE_ACTIVE_ENROLLMENT")
    level = student["placement_efl_level"]
    if level < section["min_efl_level"] or level > section["max_efl_level"]:
        raise ApiError("ERR_EFL_LEVEL_OUT_OF_RANGE")
    if section["seats_taken"] >= section["seats_total"]:
        raise ApiError("ERR_SECTION_CAPACITY_EXCEEDED")

    enrollment = new_record(store.enrollments, {
        "student_id": student["id"],
        "class_section_id": section["id"],
        "status": "ACTIVE",
        "entry_efl_level": level,
        "posted_hours": 0.0,
        "post_test_eligible": False,
        "withdrawn_at": None,
        "exit_reason": None,
        "_posted_hours": Decimal("0.00"),
    })

    section["seats_taken"] += 1
    recount_section_seats(section)
    touch(section)

    student["active_enrollment_count"] += 1
    if student["intake_status"] == "PLACED":
        student["intake_status"] = "ENROLLED"
    touch(student)

    return created(pub(enrollment))


@bp.post("/enrollments/<enrollment_id>/withdraw")
def withdraw_enrollment(enrollment_id):
    auth("ProgramCoordinator", "Instructor")
    enrollment = find_enrollment(enrollment_id)
    data = body()
    exit_reason = req_str(data, "exit_reason")
    if enrollment["status"] != "ACTIVE":
        raise ApiError("ERR_ENROLLMENT_NOT_ACTIVE")

    enrollment["status"] = "WITHDRAWN"
    enrollment["withdrawn_at"] = fmt_clock(clock())
    enrollment["exit_reason"] = exit_reason
    touch(enrollment)

    section = store.sections.get(enrollment["class_section_id"])
    if section is not None:
        if section["seats_taken"] > 0:
            section["seats_taken"] -= 1
        recount_section_seats(section)
        touch(section)

    student = store.students.get(enrollment["student_id"])
    if student is not None:
        student["active_enrollment_count"] -= 1
        if student["active_enrollment_count"] < 0:
            student["active_enrollment_count"] = 0
        if student["active_enrollment_count"] == 0 and student["intake_status"] == "ENROLLED":
            student["intake_status"] = "PLACED"
        touch(student)

    return ok(pub(enrollment))


@bp.get("/enrollments/<enrollment_id>")
def read_enrollment(enrollment_id):
    role, user_id = auth("ProgramCoordinator", "StateAuthority", "Instructor",
                         "Registrar", "Student")
    enrollment = find_enrollment(enrollment_id)
    if role == "Student" and user_id != enrollment["student_id"]:
        deny_scope()
    return ok(pub(enrollment))


@bp.get("/enrollments")
def list_enrollments():
    auth("ProgramCoordinator", "StateAuthority", "Instructor", "Registrar")
    limit, offset = pagination()
    rows = list(store.enrollments.values())
    for key in ("student_id", "class_section_id", "status"):
        wanted = request.args.get(key)
        if wanted is not None:
            rows = [r for r in rows if r[key] == wanted]
    return paginate(by_created(rows), limit, offset)


# --------------------------------------------------------------------------
# attendance entries
# --------------------------------------------------------------------------

@bp.post("/enrollments/<enrollment_id>/attendance-entries")
def post_attendance(enrollment_id):
    role, user_id = auth("Instructor", "ProgramCoordinator")
    enrollment = find_enrollment(enrollment_id)
    data = body()
    date_raw, date_value = req_date(data, "attendance_date")
    hours = req_dec(data, "hours", exclusive_min=0, maximum=8, multiple_of="0.25")

    if enrollment["status"] != "ACTIVE":
        raise ApiError("ERR_ENROLLMENT_NOT_ACTIVE")
    if date_value > clock().date():
        raise ApiError("ERR_INVALID_EFFECTIVE_WINDOW")

    entry = new_record(store.attendance, {
        "enrollment_id": enrollment["id"],
        "attendance_date": date_raw,
        "hours": hours_out(hours),
        "status": "POSTED",
        "void_reason": None,
        "posted_by_user_id": user_id,
        "_hours": hours,
    })

    enrollment["_posted_hours"] = q2(enrollment["_posted_hours"] + hours)
    enrollment["posted_hours"] = hours_out(enrollment["_posted_hours"])
    enrollment["post_test_eligible"] = calc.hours_gate_ok(enrollment)
    touch(enrollment)

    student = store.students.get(enrollment["student_id"])
    if student is not None:
        recompute_student_hours(student)
        touch(student)

    return created(pub(entry))


@bp.post("/attendance-entries/<entry_id>/void")
def void_attendance(entry_id):
    auth("Instructor", "ProgramCoordinator")
    entry = find_entry(entry_id)
    data = body()
    void_reason = req_str(data, "void_reason")
    expected = req_int(data, "expected_enrollment_version")

    enrollment = store.enrollments.get(entry["enrollment_id"])
    if enrollment is None:
        raise ApiError("ERR_ENROLLMENT_NOT_FOUND")
    if expected != enrollment["version"]:
        raise ApiError("ERR_STALE_ENROLLMENT_VERSION")
    if entry["status"] != "POSTED":
        raise ApiError("ERR_ATTENDANCE_ALREADY_VOIDED")
    if enrollment["status"] != "ACTIVE":
        raise ApiError("ERR_ENROLLMENT_NOT_ACTIVE")

    cascades.void_attendance(entry, void_reason)
    return ok(pub(entry))


@bp.get("/attendance-entries/<entry_id>")
def read_attendance(entry_id):
    auth("Instructor", "ProgramCoordinator", "StateAuthority")
    return ok(pub(find_entry(entry_id)))


@bp.get("/attendance-entries")
def list_attendance():
    auth("Instructor", "ProgramCoordinator", "StateAuthority")
    limit, offset = pagination()
    rows = list(store.attendance.values())
    for key in ("enrollment_id", "status"):
        wanted = request.args.get(key)
        if wanted is not None:
            rows = [r for r in rows if r[key] == wanted]
    return paginate(by_created(rows), limit, offset)


# --------------------------------------------------------------------------
# test events
# --------------------------------------------------------------------------

@bp.post("/test-events")
def create_test_event():
    auth("Registrar", "ProgramCoordinator")
    data = body()
    student_id = req_fk(data, "student_id")
    purpose = req_enum(data, "purpose", calc.TEST_PURPOSES)
    test_form = req_enum(data, "test_form", calc.TEST_FORMS)
    scheduled_raw, scheduled_dt = req_dt(data, "scheduled_for")
    enrollment_id = opt_fk(data, "enrollment_id")
    if purpose == "POST_TEST" and enrollment_id is None:
        raise ApiError("ERR_INVALID_REQUEST")

    student = find_student(student_id)
    enrollment = find_enrollment(enrollment_id) if enrollment_id is not None else None

    if student["intake_status"] not in ("ORIENTED", "PLACED", "ENROLLED"):
        raise ApiError("ERR_STUDENT_NOT_ORIENTED")

    if purpose == "POST_TEST" and not calc.interval_gate_ok(student["id"]):
        raise ApiError("ERR_POST_TEST_INTERVAL_NOT_MET")

    if scheduled_dt < clock():
        raise ApiError("ERR_INVALID_SESSION_WINDOW")

    if purpose == "POST_TEST" and not calc.hours_gate_ok(enrollment):
        raise ApiError("ERR_POST_TEST_HOURS_NOT_MET")

    for event in store.test_events.values():
        if (event["student_id"] == student["id"]
                and event["purpose"] == purpose
                and event["status"] == "SCHEDULED"):
            raise ApiError("ERR_TEST_EVENT_CONFLICT")

    event = new_record(store.test_events, {
        "student_id": student["id"],
        "enrollment_id": enrollment["id"] if enrollment is not None else None,
        "purpose": purpose,
        "test_form": test_form,
        "scheduled_for": scheduled_raw,
        "test_date": None,
        "scale_score": None,
        "efl_level": None,
        "status": "SCHEDULED",
        "invalidation_reason": None,
        "_scheduled_for": scheduled_dt,
        "_test_date": None,
    })
    return created(pub(event))


@bp.post("/test-events/<event_id>/score")
def score_test_event(event_id):
    auth("Instructor")
    event = find_test_event(event_id)
    data = body()
    scale_score = req_int(data, "scale_score", minimum=0, maximum=999)
    if event["status"] != "SCHEDULED":
        raise ApiError("ERR_TEST_EVENT_NOT_SCHEDULED")

    now = clock()
    event["status"] = "SCORED"
    event["scale_score"] = scale_score
    event["test_date"] = fmt_clock(now)
    event["_test_date"] = now
    event["efl_level"] = calc.efl_level_for(event["test_form"], scale_score)
    touch(event)

    if event["purpose"] == "PRE_TEST":
        earliest = calc.earliest_scored_pre_test(event["student_id"])
        if earliest is not None and earliest["id"] == event["id"]:
            student = store.students.get(event["student_id"])
            if student is not None:
                student["placement_efl_level"] = event["efl_level"]
                if student["intake_status"] == "ORIENTED":
                    student["intake_status"] = "PLACED"
                touch(student)

    return ok(pub(event))


@bp.get("/test-events/<event_id>")
def read_test_event(event_id):
    role, user_id = auth("Registrar", "ProgramCoordinator", "StateAuthority", "Student")
    event = find_test_event(event_id)
    if role == "Student" and user_id != event["student_id"]:
        deny_scope()
    return ok(pub(event))


@bp.get("/test-events")
def list_test_events():
    auth("Registrar", "ProgramCoordinator", "StateAuthority")
    limit, offset = pagination()
    rows = list(store.test_events.values())
    for key in ("student_id", "enrollment_id", "purpose", "status"):
        wanted = request.args.get(key)
        if wanted is not None:
            rows = [r for r in rows if r.get(key) == wanted]
    return paginate(by_created(rows), limit, offset)
