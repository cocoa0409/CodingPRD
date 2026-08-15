"""Payload factories — one per creatable resource, input fields only (PRD §3)."""
from typing import Optional

from .constants import DEADLINES, TEST_DEFAULTS

DEFAULTS = {
    "ACADEMIC_YEAR": "2027-2028",
    "FIRST_NAME": "Ann",
    "LAST_NAME": "Able",
    "DATE_OF_BIRTH": "2013-05-01",
    "REPORTED_INCOME_CENTS": 9_500_000,
    "HOUSEHOLD_SIZE": 4,
    "APPEAL_REASON": "family circumstances changed",
}


def create_cycle_payload(**overrides) -> dict:
    defaults = {
        "academic_year": DEFAULTS["ACADEMIC_YEAR"],
        "early_deadline_at": DEADLINES["EARLY"],
        "regular_deadline_at": DEADLINES["REGULAR"],
        "reenroll_response_deadline_at": DEADLINES["REENROLL"],
        "melt_deadline_at": DEADLINES["MELT"],
        "aid_budget_total_cents": TEST_DEFAULTS["AID_BUDGET_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_grade_section_payload(cycle_id: str, **overrides) -> dict:
    defaults = {
        "cycle_id": cycle_id,
        "grade_level": "G9",
        "capacity": TEST_DEFAULTS["SECTION_CAPACITY"],
        "tuition_cents": TEST_DEFAULTS["TUITION_CENTS"],
        "max_aid_seat_pct": TEST_DEFAULTS["MAX_AID_SEAT_PCT"],
    }
    defaults.update(overrides)
    return defaults


def create_applicant_payload(family_id: str, **overrides) -> dict:
    defaults = {
        "family_id": family_id,
        "first_name": DEFAULTS["FIRST_NAME"],
        "last_name": DEFAULTS["LAST_NAME"],
        "date_of_birth": DEFAULTS["DATE_OF_BIRTH"],
    }
    defaults.update(overrides)
    return defaults


def create_student_payload(family_id: str, current_grade_section_id: str,
                           **overrides) -> dict:
    defaults = {
        "family_id": family_id,
        "first_name": DEFAULTS["FIRST_NAME"],
        "last_name": DEFAULTS["LAST_NAME"],
        "current_grade_section_id": current_grade_section_id,
    }
    defaults.update(overrides)
    return defaults


def create_application_payload(applicant_id: str, cycle_id: str,
                               grade_section_id: str, **overrides) -> dict:
    defaults = {
        "applicant_id": applicant_id,
        "cycle_id": cycle_id,
        "grade_section_id": grade_section_id,
        "round": "EARLY",
    }
    defaults.update(overrides)
    return defaults


def create_evaluation_payload(application_id: str, kind: str, **overrides) -> dict:
    """Kind-specific fields are exclusive per PRD §3.3: TEST carries
    test_session_id, INTERVIEW carries interviewer_id."""
    defaults = {
        "application_id": application_id,
        "kind": kind,
        "scheduled_start": "2026-10-10T09:00:00Z",
        "scheduled_end": "2026-10-10T10:00:00Z",
    }
    if kind == "TEST":
        defaults["test_session_id"] = overrides.pop("test_session_id", None)
    else:
        defaults["interviewer_id"] = overrides.pop("interviewer_id", "int-a")
    defaults.update(overrides)
    return defaults


def create_test_session_payload(cycle_id: str, **overrides) -> dict:
    defaults = {
        "cycle_id": cycle_id,
        "session_start": "2026-10-10T09:00:00Z",
        "session_end": "2026-10-10T12:00:00Z",
        "room_capacity": TEST_DEFAULTS["SESSION_CAPACITY"],
    }
    defaults.update(overrides)
    return defaults


def create_aid_application_payload(application_id: str, **overrides) -> dict:
    defaults = {
        "application_id": application_id,
        "reported_annual_income_cents": DEFAULTS["REPORTED_INCOME_CENTS"],
        "household_size": DEFAULTS["HOUSEHOLD_SIZE"],
    }
    defaults.update(overrides)
    return defaults


def resubmit_income_payload(reported_annual_income_cents: int,
                            household_size: int) -> dict:
    return {
        "reported_annual_income_cents": reported_annual_income_cents,
        "household_size": household_size,
    }


def create_reenrollment_offer_payload(student_id: str, cycle_id: str,
                                      expected_student_version: int,
                                      **overrides) -> dict:
    defaults = {
        "student_id": student_id,
        "cycle_id": cycle_id,
        "expected_student_version": expected_student_version,
    }
    defaults.update(overrides)
    return defaults
