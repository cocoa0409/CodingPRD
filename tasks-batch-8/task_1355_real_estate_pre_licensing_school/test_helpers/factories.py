"""Payload factories — one per entity, input fields only (PRD §3/§4)."""
from .constants import TEST_DEFAULTS

_seq = {"n": 0}


def _next() -> int:
    _seq["n"] += 1
    return _seq["n"]


def create_school_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "school_name": TEST_DEFAULTS["SCHOOL_NAME"],
        "school_code": f"{TEST_DEFAULTS['SCHOOL_CODE']}{n:04d}",
        "home_state_code": TEST_DEFAULTS["HOME_STATE"],
    }
    defaults.update(overrides)
    return defaults


def create_course_payload(school_id, **overrides) -> dict:
    n = _next()
    defaults = {
        "school_id": school_id,
        "course_code": f"{TEST_DEFAULTS['COURSE_CODE']}-{n}",
        "title": TEST_DEFAULTS["COURSE_TITLE"],
        "course_type": "PRE_LICENSING",
        "required_seat_minutes": TEST_DEFAULTS["REQUIRED_SEAT_MINUTES"],
        "tuition_cents": TEST_DEFAULTS["TUITION_CENTS"],
        "pass_score_pct": TEST_DEFAULTS["PASS_SCORE_PCT"],
        "completion_deadline_days": TEST_DEFAULTS["COMPLETION_DEADLINE_DAYS"],
        "ce_credit_hours": 0,
    }
    defaults.update(overrides)
    return defaults


def create_course_approval_payload(state_code=None, **overrides) -> dict:
    defaults = {"state_code": state_code or TEST_DEFAULTS["HOME_STATE"]}
    defaults.update(overrides)
    return defaults


def decide_approval_payload(**overrides) -> dict:
    defaults = {
        "decision": "APPROVED",
        "valid_from": TEST_DEFAULTS["APPROVAL_VALID_FROM"],
        "valid_until": TEST_DEFAULTS["APPROVAL_VALID_UNTIL"],
    }
    defaults.update(overrides)
    return defaults


def create_instructor_payload(school_id, **overrides) -> dict:
    n = _next()
    defaults = {
        "school_id": school_id,
        "full_name": f"Ira Instructor {n}",
        "license_number": f"INS-{n:04d}",
    }
    defaults.update(overrides)
    return defaults


def create_instructor_approval_payload(state_code=None, **overrides) -> dict:
    defaults = {"state_code": state_code or TEST_DEFAULTS["HOME_STATE"]}
    defaults.update(overrides)
    return defaults


def create_offering_payload(course_id, instructor_id, **overrides) -> dict:
    defaults = {
        "course_id": course_id,
        "instructor_id": instructor_id,
        "state_code": TEST_DEFAULTS["HOME_STATE"],
        "start_date": TEST_DEFAULTS["OFFERING_START"],
        "end_date": TEST_DEFAULTS["OFFERING_END"],
        "capacity": 2,
        "delivery_mode": "IN_PERSON",
    }
    defaults.update(overrides)
    return defaults


def create_student_payload(school_id, **overrides) -> dict:
    n = _next()
    defaults = {
        "school_id": school_id,
        "full_name": f"Student {n}",
        "email": f"student{n}@example.com",
        "license_goal_state": TEST_DEFAULTS["HOME_STATE"],
    }
    defaults.update(overrides)
    return defaults


def create_enrollment_payload(offering_id, student_id=None, **overrides) -> dict:
    defaults = {"offering_id": offering_id}
    if student_id is not None:
        defaults["student_id"] = student_id
    defaults.update(overrides)
    return defaults


def create_attendance_payload(session_date=None, minutes=60, **overrides) -> dict:
    defaults = {
        "session_date": session_date or "2026-09-03",
        "minutes": minutes,
    }
    defaults.update(overrides)
    return defaults


def create_exam_attempt_payload(proctor_instructor_id, **overrides) -> dict:
    defaults = {
        "scheduled_at": TEST_DEFAULTS["EXAM_SCHEDULED_AT"],
        "proctor_instructor_id": proctor_instructor_id,
    }
    defaults.update(overrides)
    return defaults


def withdraw_payload(reason="VOLUNTARY", **overrides) -> dict:
    defaults = {"reason": reason}
    defaults.update(overrides)
    return defaults


def pay_payload(amount_cents, **overrides) -> dict:
    defaults = {"amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults


def create_credit_report_payload(school_id, period_start, period_end, **overrides) -> dict:
    defaults = {
        "school_id": school_id,
        "period_start": period_start,
        "period_end": period_end,
    }
    defaults.update(overrides)
    return defaults


def create_amendment_payload(reason, expected_credit_report_version, **overrides) -> dict:
    defaults = {
        "reason": reason,
        "expected_credit_report_version": expected_credit_report_version,
    }
    defaults.update(overrides)
    return defaults


def create_grant_payload(course_id, home_state_code, recognized_state_code,
                         expected_course_version, **overrides) -> dict:
    defaults = {
        "course_id": course_id,
        "home_state_code": home_state_code,
        "recognized_state_code": recognized_state_code,
        "expected_course_version": expected_course_version,
    }
    defaults.update(overrides)
    return defaults


def update_offering_payload(expected_offering_version, **overrides) -> dict:
    defaults = {"expected_offering_version": expected_offering_version}
    defaults.update(overrides)
    return defaults
