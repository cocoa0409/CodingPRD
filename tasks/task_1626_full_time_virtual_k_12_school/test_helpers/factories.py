"""Payload factories — one per entity, input fields only.

Derived/system fields (attendance_status, funding totals, seats_booked,
current_caseload, claimable_days, proration_mode, issued_at, return_due_date,
clawback_cents, version, ...) are server-maintained and never sent by clients.
"""
from .constants import TEST_DEFAULTS


def create_district_payload(**overrides) -> dict:
    defaults = {
        "district_code": "D-100",
        "state_code": "CA",
        "funding_rate_cents": TEST_DEFAULTS["FUNDING_RATE_CENTS"],
        "enrollment_cap": TEST_DEFAULTS["ENROLLMENT_CAP"],
    }
    defaults.update(overrides)
    return defaults


def create_student_payload(district_of_residence_id, **overrides) -> dict:
    defaults = {
        "legal_name": "Test Student",
        "date_of_birth": TEST_DEFAULTS["DATE_OF_BIRTH"],
        "grade_level": TEST_DEFAULTS["GRADE_LEVEL"],
        "district_of_residence_id": district_of_residence_id,
    }
    defaults.update(overrides)
    return defaults


def create_stipend_payload(student_id, **overrides) -> dict:
    defaults = {
        "student_id": student_id,
        "stipend_type": "DEVICE",
        "amount_cents": TEST_DEFAULTS["STIPEND_AMOUNT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_teacher_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Teacher",
        "certification_state_codes": ["CA"],
        "caseload_cap": TEST_DEFAULTS["CASELOAD_CAP"],
    }
    defaults.update(overrides)
    return defaults


def create_teacher_assignment_payload(teacher_id, student_id, **overrides) -> dict:
    defaults = {
        "teacher_id": teacher_id,
        "student_id": student_id,
        "subject": "MATH",
    }
    defaults.update(overrides)
    return defaults


def create_attendance_payload(student_id, **overrides) -> dict:
    defaults = {
        "student_id": student_id,
        "attendance_date": "2026-08-03T00:00:00Z",
        "synchronous_minutes": 300,
        "engagement_check_ins": 3,
    }
    defaults.update(overrides)
    return defaults


def create_assessment_window_payload(**overrides) -> dict:
    defaults = {
        "assessment_name": "Fall Math",
        "subject": "MATH",
        "window_start": "2026-08-10T08:00:00Z",
        "window_end": "2026-08-12T17:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_test_site_payload(**overrides) -> dict:
    defaults = {
        "site_name": "Test Site",
        "state_code": "CA",
        "seat_capacity": TEST_DEFAULTS["SEAT_CAPACITY"],
    }
    defaults.update(overrides)
    return defaults


def create_proctor_assignment_payload(student_id, assessment_window_id,
                                      test_site_id, expected_test_site_version,
                                      **overrides) -> dict:
    defaults = {
        "student_id": student_id,
        "assessment_window_id": assessment_window_id,
        "test_site_id": test_site_id,
        "expected_test_site_version": expected_test_site_version,
    }
    defaults.update(overrides)
    return defaults


def create_service_delivery_payload(student_id, provider_id, **overrides) -> dict:
    defaults = {
        "student_id": student_id,
        "service_type": "COUNSELING",
        "scheduled_at": "2026-08-10T10:00:00Z",
        "duration_minutes": TEST_DEFAULTS["SERVICE_DURATION_MINUTES"],
        "provider_id": provider_id,
    }
    defaults.update(overrides)
    return defaults
