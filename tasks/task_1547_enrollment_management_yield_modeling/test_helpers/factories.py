"""Payload factories — one per creatable resource, input fields only."""
import uuid

from .constants import (
    APP_DEADLINE,
    APP_OPENS,
    CENSUS,
    DEPOSIT_DEADLINE,
    REVIEW_WINDOW_END,
    REVIEW_WINDOW_START,
    TEST_DEFAULTS,
)


def _unique_email() -> str:
    return f"applicant-{uuid.uuid4().hex[:10]}@example.edu"


def create_cycle_payload(**overrides) -> dict:
    defaults = {
        "name": TEST_DEFAULTS["CYCLE_NAME"],
        "application_opens_at": APP_OPENS,
        "application_deadline_at": APP_DEADLINE,
        "deposit_deadline_at": DEPOSIT_DEADLINE,
        "census_at": CENSUS,
        "target_class_size": TEST_DEFAULTS["TARGET_CLASS_SIZE"],
    }
    defaults.update(overrides)
    return defaults


def create_program_payload(cycle_id, **overrides) -> dict:
    defaults = {
        "cycle_id": cycle_id,
        "name": "Computer Science",
        "capacity_seats": TEST_DEFAULTS["CAPACITY_SEATS"],
        "target_enrollment": TEST_DEFAULTS["TARGET_ENROLLMENT"],
        "tuition_cents": TEST_DEFAULTS["TUITION_CENTS"],
        "scholarship_budget_cents": TEST_DEFAULTS["SCHOLARSHIP_BUDGET_CENTS"],
        "deposit_amount_cents": TEST_DEFAULTS["DEPOSIT_AMOUNT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_applicant_payload(cycle_id, **overrides) -> dict:
    defaults = {
        "cycle_id": cycle_id,
        "full_name": "Test Applicant",
        "email": _unique_email(),
        "applicant_type": "FIRST_YEAR",
        "inquiry_source": "WEB_FORM",
        "distance_band": "LOCAL",
    }
    defaults.update(overrides)
    return defaults


def create_application_payload(applicant_id, program_id, cycle_id,
                               **overrides) -> dict:
    defaults = {
        "applicant_id": applicant_id,
        "program_id": program_id,
        "cycle_id": cycle_id,
        "academic_score": TEST_DEFAULTS["ACADEMIC_SCORE"],
        "efc_cents": TEST_DEFAULTS["EFC_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_review_payload(application_id, reader_id, **overrides) -> dict:
    defaults = {
        "application_id": application_id,
        "reader_id": reader_id,
        "window_start_at": REVIEW_WINDOW_START,
        "window_end_at": REVIEW_WINDOW_END,
    }
    defaults.update(overrides)
    return defaults


def submit_review_payload(**overrides) -> dict:
    defaults = {
        "score_academic": 80,
        "score_fit": 80,
        "recommendation": "ADMIT",
    }
    defaults.update(overrides)
    return defaults


def create_aid_offer_payload(application_id, fund_type,
                             expected_application_version) -> dict:
    return {
        "application_id": application_id,
        "fund_type": fund_type,
        "expected_application_version": expected_application_version,
    }


def create_deposit_payload(application_id, amount_cents) -> dict:
    return {
        "application_id": application_id,
        "amount_cents": amount_cents,
    }


def create_intervention_payload(application_id, advisor_id,
                                intervention_type, window_start_at,
                                window_end_at) -> dict:
    return {
        "application_id": application_id,
        "advisor_id": advisor_id,
        "intervention_type": intervention_type,
        "window_start_at": window_start_at,
        "window_end_at": window_end_at,
    }
