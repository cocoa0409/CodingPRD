"""Payload factories — one per entity, input fields only."""
import itertools

from .constants import STANDARD_YEAR

_counter = itertools.count(1)


def _n() -> int:
    return next(_counter)


def create_school_year_payload(**overrides) -> dict:
    defaults = dict(STANDARD_YEAR)
    defaults.update(overrides)
    return defaults


def create_security_plan_payload(**overrides) -> dict:
    defaults = {"plan_document": f"Security and safety plan {_n()}"}
    defaults.update(overrides)
    return defaults


def create_closure_payload(**overrides) -> dict:
    defaults = {
        "start_date": "2026-09-07",
        "end_date": "2026-09-08",
        "reason": f"Holiday {_n()}",
    }
    defaults.update(overrides)
    return defaults


def create_family_payload(**overrides) -> dict:
    i = _n()
    defaults = {
        "family_name": f"Family {i}",
        "primary_email": f"family{i}@example.org",
        "membership_status": "MEMBER",
    }
    defaults.update(overrides)
    return defaults


def create_student_payload(**overrides) -> dict:
    i = _n()
    defaults = {
        "full_name": f"Student {i}",
        "grade": "G3",
        "hebrew_level": "BEGINNER",
    }
    defaults.update(overrides)
    return defaults


def create_teacher_payload(**overrides) -> dict:
    i = _n()
    defaults = {
        "full_name": f"Teacher {i}",
        "email": f"teacher{i}@example.org",
        "background_check_cleared": True,
    }
    defaults.update(overrides)
    return defaults


def create_section_payload(**overrides) -> dict:
    i = _n()
    defaults = {
        "grade": "G3",
        "hebrew_level": "BEGINNER",
        "capacity": 5,
        "room": f"R{i}",
        "day_of_week": "SUN",
        "start_time": "10:00",
        "end_time": "11:30",
    }
    defaults.update(overrides)
    return defaults


def create_enrollment_payload(student_id, expected_section_version, **overrides) -> dict:
    payload = {
        "student_id": student_id,
        "expected_section_version": expected_section_version,
    }
    payload.update(overrides)
    return payload


def create_invoice_payload(school_year_id, expected_family_version, **overrides) -> dict:
    payload = {
        "school_year_id": school_year_id,
        "expected_family_version": expected_family_version,
    }
    payload.update(overrides)
    return payload


def create_payment_payload(**overrides) -> dict:
    defaults = {"amount_cents": 20000, "method": "CARD"}
    defaults.update(overrides)
    return defaults


def create_application_payload(school_year_id, **overrides) -> dict:
    payload = {"school_year_id": school_year_id, "reason": f"Need {_n()}"}
    payload.update(overrides)
    return payload


def create_session_payload(**overrides) -> dict:
    defaults = {"session_date": "2026-09-13"}
    defaults.update(overrides)
    return defaults


def create_attendance_payload(student_id, status="PRESENT", **overrides) -> dict:
    payload = {"entries": [{"student_id": student_id, "status": status}]}
    payload.update(overrides)
    return payload


def create_volunteer_entry_payload(**overrides) -> dict:
    defaults = {"hours": 1, "note": f"Volunteer work {_n()}"}
    defaults.update(overrides)
    return defaults
