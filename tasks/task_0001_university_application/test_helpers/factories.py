"""Payload factories — one per entity, input fields only."""
from .constants import (
    DEFAULT_IN_STATE_TUITION_CENTS,
    DEFAULT_OUT_OF_STATE_TUITION_CENTS,
    DEFAULT_INTERNATIONAL_TUITION_CENTS,
    DEFAULT_TARGET_CLASS_SIZE,
    DEFAULT_ASSUMED_YIELD_RATE,
    DEFAULT_HOUSEHOLD_INCOME_CENTS,
    DEFAULT_HOUSEHOLD_SIZE,
)


def create_applicant_payload(**overrides) -> dict:
    """POST /applicants — Anonymous self-registration."""
    defaults = {
        "email": "applicant@u.edu",
        "full_name": "Test Applicant",
        "gpa_unweighted": 3.50,
        "sat_total": 1300,
        "residency": "IN_STATE",
    }
    defaults.update(overrides)
    return defaults


def create_school_payload(**overrides) -> dict:
    """POST /schools — PlatformAdmin."""
    defaults = {
        "name": "Test University",
        "state_code": "MA",
        "admission_track": "REGULAR",
        "deadline_iso": "2026-09-30T00:00:00Z",
        "decision_release_iso": "2027-03-15T00:00:00Z",
        "target_class_size": DEFAULT_TARGET_CLASS_SIZE,
        "assumed_yield_rate": DEFAULT_ASSUMED_YIELD_RATE,
        "in_state_tuition_cents": DEFAULT_IN_STATE_TUITION_CENTS,
        "out_of_state_tuition_cents": DEFAULT_OUT_OF_STATE_TUITION_CENTS,
        "international_tuition_cents": DEFAULT_INTERNATIONAL_TUITION_CENTS,
    }
    defaults.update(overrides)
    return defaults


def create_application_payload(applicant_id: str, school_id: str, **overrides) -> dict:
    """POST /applications — Applicant."""
    defaults = {
        "applicant_id": applicant_id,
        "school_id": school_id,
    }
    defaults.update(overrides)
    return defaults


def create_essay_payload(application_id: str, prompt_code: str = "PERSONAL", **overrides) -> dict:
    """POST /essays — Applicant."""
    defaults = {
        "application_id": application_id,
        "prompt_code": prompt_code,
        "word_count": 5,
        "text": "Lorem ipsum dolor sit amet.",
        "completed": True,
    }
    defaults.update(overrides)
    return defaults


def create_recommendation_request_payload(
    applicant_id: str, school_id: str, recommender_email: str, **overrides,
) -> dict:
    """POST /recommendation-requests — Applicant."""
    defaults = {
        "applicant_id": applicant_id,
        "school_id": school_id,
        "recommender_email": recommender_email,
    }
    defaults.update(overrides)
    return defaults


def create_financial_aid_profile_payload(
    applicant_id: str, profile_type: str = "FAFSA", **overrides,
) -> dict:
    """POST /financial-aid-profiles — Applicant."""
    defaults = {
        "applicant_id": applicant_id,
        "profile_type": profile_type,
        "household_income_cents": DEFAULT_HOUSEHOLD_INCOME_CENTS,
        "household_size": DEFAULT_HOUSEHOLD_SIZE,
    }
    defaults.update(overrides)
    return defaults


def create_aid_package_payload(
    application_id: str,
    grant_cents: int = 500_000,
    loan_cents: int = 400_000,
    work_study_cents: int = 100_000,
    **overrides,
) -> dict:
    """POST /aid-packages — FinancialAidOfficer."""
    defaults = {
        "application_id": application_id,
        "grant_cents": grant_cents,
        "loan_cents": loan_cents,
        "work_study_cents": work_study_cents,
    }
    defaults.update(overrides)
    return defaults
