"""Payload factories — one per entity, input fields only (PRD §3)."""
from typing import Optional

from .constants import TEST_DEFAULTS


def create_student_payload(**overrides) -> dict:
    defaults = {
        "sevis_id": TEST_DEFAULTS["SEVIS_ID"],
        "full_name": TEST_DEFAULTS["FULL_NAME"],
        "email": TEST_DEFAULTS["EMAIL"],
        "date_of_birth": TEST_DEFAULTS["DATE_OF_BIRTH"],
        "country_of_citizenship": TEST_DEFAULTS["COUNTRY"],
        "degree_level": TEST_DEFAULTS["DEGREE_LEVEL"],
    }
    defaults.update(overrides)
    return defaults


def create_financial_document_payload(**overrides) -> dict:
    defaults = {
        "document_type": "BANK_STATEMENT",
        "amount_usd_cents": TEST_DEFAULTS["FUNDING_CENTS"],
        "issue_date": TEST_DEFAULTS["FUNDING_ISSUE_DATE"],
    }
    defaults.update(overrides)
    return defaults


def review_document_payload(decision: str = "VERIFIED",
                            note: Optional[str] = None) -> dict:
    payload = {"decision": decision}
    if note is not None:
        payload["note"] = note
    return payload


def create_sevis_record_payload(**overrides) -> dict:
    defaults = {
        "program_start_date": TEST_DEFAULTS["PROGRAM_START"],
        "program_end_date": TEST_DEFAULTS["PROGRAM_END"],
    }
    defaults.update(overrides)
    return defaults


def create_i20_form_payload(sevis_record_id: str, **overrides) -> dict:
    defaults = {
        "sevis_record_id": sevis_record_id,
        "program_name": TEST_DEFAULTS["PROGRAM_NAME"],
        "tuition_cents": TEST_DEFAULTS["TUITION_CENTS"],
        "living_cents": TEST_DEFAULTS["LIVING_CENTS"],
        "insurance_cents": TEST_DEFAULTS["INSURANCE_CENTS"],
        "other_cents": TEST_DEFAULTS["OTHER_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_term_enrollment_payload(student_id: str, **overrides) -> dict:
    defaults = {
        "student_id": student_id,
        "term_code": TEST_DEFAULTS["TERM_CODE"],
        "term_start_date": TEST_DEFAULTS["TERM_START"],
        "term_end_date": TEST_DEFAULTS["TERM_END"],
        "enrolled_credits": TEST_DEFAULTS["ENROLLED_CREDITS"],
    }
    defaults.update(overrides)
    return defaults


def create_rcl_payload(enrollment_id: str, **overrides) -> dict:
    defaults = {
        "enrollment_id": enrollment_id,
        "reason_category": "ACADEMIC",
        "requested_credits": 6,
    }
    defaults.update(overrides)
    return defaults


def rcl_decision_payload(decision: str = "APPROVED",
                         note: Optional[str] = None) -> dict:
    payload = {"decision": decision}
    if note is not None:
        payload["note"] = note
    return payload


def create_employment_authorization_payload(student_id: str, **overrides) -> dict:
    defaults = {
        "student_id": student_id,
        "auth_type": "CPT",
        "hours_per_week": 20,
        "start_date": "2026-09-01",
        "end_date": "2026-12-11",
    }
    defaults.update(overrides)
    return defaults


def authorization_transition_payload(action: str, outcome: Optional[str] = None,
                                     uscis_receipt_number: Optional[str] = None,
                                     note: Optional[str] = None) -> dict:
    payload = {"action": action}
    if outcome is not None:
        payload["outcome"] = outcome
    if uscis_receipt_number is not None:
        payload["uscis_receipt_number"] = uscis_receipt_number
    if note is not None:
        payload["note"] = note
    return payload


def create_employment_period_payload(**overrides) -> dict:
    defaults = {
        "employer_name": "Acme Corp",
        "start_date": "2027-01-01",
        "hours_per_week": 40,
    }
    defaults.update(overrides)
    return defaults


def create_travel_endorsement_payload(expected_i20_form_version: int,
                                      **overrides) -> dict:
    defaults = {
        "expected_i20_form_version": expected_i20_form_version,
        "travel_departure_date": "2026-12-12",
        "travel_return_date": "2027-01-10",
    }
    defaults.update(overrides)
    return defaults


def create_transfer_request_payload(**overrides) -> dict:
    defaults = {
        "direction": "OUT",
        "target_school_code": "ABC123",
        "release_date": "2026-09-01",
    }
    defaults.update(overrides)
    return defaults


def create_program_extension_payload(new_program_end_date: str,
                                     expected_sevis_record_version: int,
                                     **overrides) -> dict:
    defaults = {
        "new_program_end_date": new_program_end_date,
        "reason": "Thesis completion",
        "expected_sevis_record_version": expected_sevis_record_version,
    }
    defaults.update(overrides)
    return defaults


def extension_decision_payload(decision: str = "APPROVED",
                               note: Optional[str] = None) -> dict:
    payload = {"decision": decision}
    if note is not None:
        payload["note"] = note
    return payload


def create_status_violation_payload(**overrides) -> dict:
    defaults = {
        "violation_type": "UNAUTHORIZED_EMPLOYMENT",
        "description": "Worked off campus without authorization",
    }
    defaults.update(overrides)
    return defaults


def violation_transition_payload(action: str, outcome: Optional[str] = None,
                                 note: Optional[str] = None) -> dict:
    payload = {"action": action}
    if outcome is not None:
        payload["outcome"] = outcome
    if note is not None:
        payload["note"] = note
    return payload


def create_address_report_payload(**overrides) -> dict:
    defaults = {
        "move_date": "2026-08-01",
        "address_line1": "1 College Ave",
        "city": "Springfield",
        "state_code": "IL",
        "postal_code": "62701",
    }
    defaults.update(overrides)
    return defaults
