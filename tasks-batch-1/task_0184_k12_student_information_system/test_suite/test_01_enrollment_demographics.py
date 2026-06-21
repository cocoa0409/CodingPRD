"""Enrollment, demographics, and basic lifecycle transitions.

Covers corner-design instances under sections `entities` and `state_machines`.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS, NON_EXISTENT_UUID,
    assert_student, assert_enrollment, assert_section,
    fixtures as fx,
)

REG = TEST_USERS["registrar_headers"]
TEACH = TEST_USERS["teacher_headers"]


def test_create_student_returns_201_with_system_fields(api):
    """PRD §3.2: "A new student begins life in PROSPECTIVE status."
    PRD §2.6: "a system-managed id, a server-minted UUID with no type prefix"
    and "an integer version that begins at its initial value and increments by
    one on each mutation."

    Design: Corner/entities/create_student_returns_201_with_system_fields
    """
    school = fx.create_school()
    resp = api.create_student(
        {"school_id": school["id"], "state_student_id": "SSID-N1", "first_name": "Ned",
         "last_name": "New", "grade_level": "4", "birth_date": "2015-06-06"},
        REG,
    )
    data = validate_success(resp, expected_status=201)
    assert_student(data)
    assert data["status"] == "PROSPECTIVE", f"new student must be PROSPECTIVE, got {data['status']}"
    assert data["version"] == 1, f"version begins at 1, got {data['version']}"


def test_create_student_missing_required_field_returns_invalid_request(api):
    """PRD §2.5: "Malformed bodies, missing required fields, type mismatches, and
    unrecognized enum values are reported as ERR_INVALID_REQUEST with HTTP 400."

    Design: Corner/entities/create_student_missing_required_field_returns_invalid_request
    """
    school = fx.create_school()
    resp = api.create_student(
        {"school_id": school["id"], "state_student_id": "SSID-M1", "first_name": "Moe",
         "last_name": "Miss", "birth_date": "2015-06-06"},  # grade_level omitted
        REG,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400)


def test_get_student_nonexistent_returns_not_found(api):
    """PRD §2.5: "The first identifier that fails to resolve produces that
    resource's specific not-found error — ERR_SCHOOL_NOT_FOUND,
    ERR_STUDENT_NOT_FOUND, ERR_ENROLLMENT_NOT_FOUND, ERR_COURSE_NOT_FOUND,
    ERR_SECTION_NOT_FOUND, ERR_SCHEDULE_ASSIGNMENT_NOT_FOUND,
    ERR_ATTENDANCE_RECORD_NOT_FOUND, ERR_STANDARD_SCORE_NOT_FOUND,
    ERR_REPORT_CARD_NOT_FOUND, ERR_INCIDENT_NOT_FOUND, ERR_CONSEQUENCE_NOT_FOUND,
    or ERR_ADA_REPORT_NOT_FOUND — each returned with HTTP 404."

    Design: Corner/entities/get_student_nonexistent_returns_not_found
    """
    resp = api.get_student(NON_EXISTENT_UUID, REG)
    validate_error(resp, ApiErrorId.ERR_STUDENT_NOT_FOUND.value, expected_status=404)


def test_enrollment_default_fte_applied(api):
    """PRD §3.3: "plus an optional fte that defaults to 1.0 and must be greater
    than 0 and at most 1.0".

    Design: Corner/entities/enrollment_default_fte_applied
    """
    school = fx.create_school()
    student = fx.create_student(school["id"])
    resp = api.create_enrollment({"student_id": student["id"], "entry_day_index": 1}, REG)
    data = validate_success(resp, expected_status=201)
    assert_enrollment(data)
    assert float(data["fte"]) == 1.0, f"default fte must be 1.0, got {data['fte']}"
    assert data["status"] == "ACTIVE", f"new enrollment must be ACTIVE, got {data['status']}"


def test_enroll_sets_student_status_enrolled_and_copies_school(api):
    """PRD §3.3: "On creation the enrollment copies its school_id from the student,
    starts in ACTIVE status, drives the student's status to ENROLLED, and
    initializes both membership_days and present_days to 0."

    Design: Corner/entities/enroll_sets_student_status_enrolled_computed
    """
    school = fx.create_school()
    student = fx.create_student(school["id"])
    enr = validate_success(
        api.create_enrollment({"student_id": student["id"], "entry_day_index": 1}, REG),
        expected_status=201,
    )
    assert enr["school_id"] == school["id"], "enrollment.school_id copied from student"
    refreshed = validate_success(api.get_student(student["id"], REG))
    assert refreshed["status"] == "ENROLLED", f"student status -> ENROLLED, got {refreshed['status']}"


def test_duplicate_state_student_id_rejected(api):
    """PRD §3.2: "The state_student_id must be unique within the school; a
    collision is rejected with ERR_DUPLICATE_STATE_STUDENT_ID."

    Design: Corner/entities/duplicate_state_student_id_rejected
    """
    school = fx.create_school()
    api.create_student(
        {"school_id": school["id"], "state_student_id": "SSID-DUP", "first_name": "One",
         "last_name": "Dup", "grade_level": "5", "birth_date": "2015-01-01"}, REG)
    resp = api.create_student(
        {"school_id": school["id"], "state_student_id": "SSID-DUP", "first_name": "Two",
         "last_name": "Dup", "grade_level": "5", "birth_date": "2015-02-01"}, REG)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_STATE_STUDENT_ID.value, expected_status=409)


def test_duplicate_course_code_rejected(api):
    """PRD §3.4: "A registrar defines a Course under a school_id with a course_code
    that must be unique within the school — a duplicate is rejected with
    ERR_DUPLICATE_COURSE_CODE".

    Design: Corner/entities/duplicate_course_code_rejected
    """
    school = fx.create_school()
    api.create_course(
        {"school_id": school["id"], "course_code": "MATH1", "title": "Math 1",
         "grading_mode": "STANDARDS"}, REG)
    resp = api.create_course(
        {"school_id": school["id"], "course_code": "MATH1", "title": "Math 1 dup",
         "grading_mode": "STANDARDS"}, REG)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_COURSE_CODE.value, expected_status=409)


def test_list_students_pagination_envelope(api):
    """PRD §2.3: "Each list response carries limit, offset, total_count, and
    has_more inside the meta object of the envelope."

    Design: Corner/entities/list_students_pagination_envelope
    """
    school = fx.create_school()
    fx.create_student(school["id"], state_student_id="SSID-L1")
    fx.create_student(school["id"], state_student_id="SSID-L2")
    resp = api.list_students(REG, params={"school_id": school["id"], "limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2, f"expected total_count 2, got {meta['total_count']}"
    assert meta["has_more"] is True, "has_more must be true when more remain"
    assert len(data) == 1, f"limit=1 must return one item, got {len(data)}"


def test_withdraw_already_withdrawn_returns_not_active(api):
    """PRD §3.3: "The withdrawal is only permitted while the enrollment is ACTIVE;
    otherwise it is rejected with ERR_ENROLLMENT_NOT_ACTIVE."

    Design: Corner/state_machines/withdraw_already_withdrawn_returns_not_active
    """
    ctx = fx.setup_enrolled_student(clock_days=2)
    enr_id = ctx["enrollment"]["id"]
    validate_success(api.withdraw_enrollment(enr_id, {"exit_day_index": 2}, REG))
    resp = api.withdraw_enrollment(enr_id, {"exit_day_index": 2}, REG)
    validate_error(resp, ApiErrorId.ERR_ENROLLMENT_NOT_ACTIVE.value, expected_status=409)


def test_mark_no_show_with_present_record_rejected(api):
    """PRD §3.3: "A no-show may only be declared when no attendance record with
    code PRESENT exists for the enrollment; if any present record is on file, the
    request is rejected with ERR_PRESENCE_ON_RECORD."

    Design: Corner/state_machines/mark_no_show_with_present_record_rejected
    """
    ctx = fx.setup_seated_student(clock_days=1, meeting_minutes=50)
    fx.post_attendance(ctx["assignment"]["id"], 1, "PRESENT")
    resp = api.mark_no_show(ctx["enrollment"]["id"], REG)
    validate_error(resp, ApiErrorId.ERR_PRESENCE_ON_RECORD.value, expected_status=409)
    refreshed = validate_success(api.get_enrollment(ctx["enrollment"]["id"], REG))
    assert refreshed["status"] == "ACTIVE", "enrollment stays ACTIVE after rejected no-show"


def test_reopen_section_when_open_rejected(api):
    """PRD §3.4: "may reopen a closed section (rejected with ERR_SECTION_NOT_CLOSED
    if it is not currently CLOSED), moving it CLOSED → OPEN."

    Design: Corner/state_machines/reopen_section_when_open_rejected
    """
    school = fx.create_school()
    course = fx.create_course(school["id"])
    section = fx.create_section(course["id"], period=1)
    resp = api.reopen_section(section["id"], REG)
    validate_error(resp, ApiErrorId.ERR_SECTION_NOT_CLOSED.value, expected_status=409)
