"""Payload factories — one per entity, input fields only.

Field names match the University Registrar PRD exactly. Each factory accepts
**overrides so tests can control the one or two values they care about.
"""
from .constants import (
    PER_CREDIT_COST_CENTS,
    REGISTRATION_OPENS_AT,
    ADD_DEADLINE,
    DROP_DEADLINE,
    WITHDRAW_DEADLINE,
    WINDOW_OPENS_AT,
)

# Monotonic counters so factory-minted unique fields never collide within a
# single fresh-DB test run.
_seq = {"n": 0}


def _next() -> int:
    _seq["n"] += 1
    return _seq["n"]


def create_program_payload(**overrides) -> dict:
    defaults = {
        "name": "BS Computer Science",
        "required_credit_hours": 120,
        "min_gpa": 2.0,
    }
    defaults.update(overrides)
    return defaults


def create_course_payload(program_id, **overrides) -> dict:
    n = _next()
    defaults = {
        "code": f"CS{n:03d}",
        "title": "Intro",
        "credit_hours": 3,
        "program_id": program_id,
    }
    defaults.update(overrides)
    return defaults


def create_course_requirement_payload(required_course_id, requirement_type, **overrides) -> dict:
    defaults = {
        "required_course_id": required_course_id,
        "requirement_type": requirement_type,
    }
    defaults.update(overrides)
    return defaults


def create_instructor_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "full_name": "Dr A",
        "email": f"instr{n}@u.edu",
        "gap_minutes": 0,
    }
    defaults.update(overrides)
    return defaults


def create_term_payload(**overrides) -> dict:
    defaults = {
        "name": "Fall 2026",
        "registration_opens_at": REGISTRATION_OPENS_AT,
        "add_deadline": ADD_DEADLINE,
        "drop_deadline": DROP_DEADLINE,
        "withdraw_deadline": WITHDRAW_DEADLINE,
        "per_credit_cost_cents": PER_CREDIT_COST_CENTS,
        "refund_full_pct": 1.0,
        "refund_partial_pct": 0.5,
    }
    defaults.update(overrides)
    return defaults


def create_section_payload(term_id, course_id, instructor_id, **overrides) -> dict:
    n = _next()
    defaults = {
        "term_id": term_id,
        "course_id": course_id,
        "instructor_id": instructor_id,
        "section_code": f"{n:03d}",
        "seat_capacity": 5,
        "waitlist_capacity": 0,
        "meeting_days": "MWF",
        "meeting_start_min": 540,
        "meeting_end_min": 590,
    }
    defaults.update(overrides)
    return defaults


def create_student_payload(program_id, **overrides) -> dict:
    n = _next()
    defaults = {
        "full_name": "Stu Test",
        "email": f"stu{n}@u.edu",
        "program_id": program_id,
    }
    defaults.update(overrides)
    return defaults


def create_appointment_payload(term_id, student_id, **overrides) -> dict:
    defaults = {
        "term_id": term_id,
        "student_id": student_id,
        "priority_tier": 1,
        "window_opens_at": WINDOW_OPENS_AT,
        "max_credit_hours": 12,
    }
    defaults.update(overrides)
    return defaults


def create_enrollment_payload(term_id, section_id, expected_section_version, **overrides) -> dict:
    defaults = {
        "term_id": term_id,
        "section_id": section_id,
        "expected_section_version": expected_section_version,
    }
    defaults.update(overrides)
    return defaults


def create_hold_payload(student_id, hold_type, **overrides) -> dict:
    defaults = {
        "student_id": student_id,
        "hold_type": hold_type,
        "reason": "test hold",
    }
    defaults.update(overrides)
    return defaults


def create_swap_request_payload(term_id, drop_enrollment_id, add_section_id,
                                expected_section_version, **overrides) -> dict:
    defaults = {
        "term_id": term_id,
        "drop_enrollment_id": drop_enrollment_id,
        "add_section_id": add_section_id,
        "expected_section_version": expected_section_version,
    }
    defaults.update(overrides)
    return defaults
