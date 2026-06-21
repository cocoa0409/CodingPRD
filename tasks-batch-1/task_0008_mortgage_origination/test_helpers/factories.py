"""Payload factories — one per entity, input fields only.

Each test starts against an empty DB (the runner restarts the server before every
test). To keep payloads unique within a single test, factories use a module-level
counter for fields where uniqueness matters (email, ssn_last4).
"""
import itertools


_applicant_counter = itertools.count(1)


def _next_email(prefix: str = "user") -> str:
    n = next(_applicant_counter)
    return f"{prefix}{n}@test.example"


def _next_ssn_last4() -> str:
    """Return a four-digit string. Wraps at 10_000."""
    # Reuse the same counter — uniqueness within a test is all we need.
    # SSN last4 must be exactly four digits.
    n = next(_applicant_counter) % 10000
    return f"{n:04d}"


# ---------------------------------------------------------------------
# Applicant
# ---------------------------------------------------------------------
def create_applicant_payload(**overrides) -> dict:
    """Minimal valid Applicant create payload (PRD §3.1)."""
    defaults = {
        "full_name": "Test Applicant",
        "email": _next_email("applicant"),
        "ssn_last4": _next_ssn_last4(),
        "annual_income_cents": 7_726_104,  # canonical front_end_dti=0.31 baseline
        "monthly_debt_cents": 50_000,
        "credit_score": 720,
        "state_code": "CA",
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------
# LoanApplication
# ---------------------------------------------------------------------
def create_loan_application_payload(applicant_id: str, **overrides) -> dict:
    """Minimal valid LoanApplication create payload (PRD §3.1)."""
    defaults = {
        "applicant_id": applicant_id,
        "property_address": "100 Test Street",
        "property_state_code": "CA",
        "loan_purpose": "PURCHASE",
        "requested_loan_amount_cents": 30_000_000,  # $300,000
        "property_value_cents": 31_578_948,  # LTV provisional = 0.95
        "loan_term_months": 360,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------
# IncomeVerification
# ---------------------------------------------------------------------
def create_income_verification_payload(application_id: str, **overrides) -> dict:
    """Minimal valid IncomeVerification create payload (PRD §3.3)."""
    defaults = {
        "application_id": application_id,
        "document_type": "W2",
        "verified_annual_income_cents": 7_800_000,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------
# AssetVerification
# ---------------------------------------------------------------------
def create_asset_verification_payload(application_id: str, **overrides) -> dict:
    """Minimal valid AssetVerification create payload (PRD §3.3)."""
    defaults = {
        "application_id": application_id,
        "asset_type": "CHECKING",
        "verified_balance_cents": 8_000_000,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------
# Appraisal
# ---------------------------------------------------------------------
def create_appraisal_payload(application_id: str, **overrides) -> dict:
    """Minimal valid Appraisal order payload (PRD §3.4) — body only carries
    application_id; appraised_value_cents is set later via /complete."""
    defaults = {
        "application_id": application_id,
    }
    defaults.update(overrides)
    return defaults


def complete_appraisal_payload(appraised_value_cents: int, **overrides) -> dict:
    """Body for POST /appraisals/{id}/complete (PRD §3.4)."""
    defaults = {"appraised_value_cents": appraised_value_cents}
    defaults.update(overrides)
    return defaults


def reconsider_appraisal_payload(
    new_appraised_value_cents: int,
    reconsideration_note: str = "Comparables suggest a different value.",
    **overrides,
) -> dict:
    """Body for POST /appraisals/{id}/reconsider (PRD §3.4)."""
    defaults = {
        "reconsideration_note": reconsideration_note,
        "new_appraised_value_cents": new_appraised_value_cents,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------
# TitleSearch
# ---------------------------------------------------------------------
def create_title_search_payload(application_id: str, **overrides) -> dict:
    """Minimal valid TitleSearch order payload (PRD §3.5)."""
    defaults = {"application_id": application_id}
    defaults.update(overrides)
    return defaults


def raise_title_exception_payload(
    exception_summary: str = "Lien on record requires release.",
    **overrides,
) -> dict:
    """Body for POST /title-searches/{id}/raise-exception (PRD §3.5)."""
    defaults = {"exception_summary": exception_summary}
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------
# RateLock
# ---------------------------------------------------------------------
def create_rate_lock_payload(
    application_id: str,
    expected_application_version: int,
    **overrides,
) -> dict:
    """Minimal valid RateLock create payload (PRD §3.6).

    `expected_application_version` is mandatory per PRD §2.5 OCC.
    """
    defaults = {
        "application_id": application_id,
        "locked_rate_bps": 687,
        "lock_term_days": 30,
        "expected_application_version": expected_application_version,
    }
    defaults.update(overrides)
    return defaults


def extend_rate_lock_payload(extend_days: int = 7, **overrides) -> dict:
    """Body for POST /rate-locks/{id}/extend (PRD §3.6)."""
    defaults = {"extend_days": extend_days}
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------
# Disclosure
# ---------------------------------------------------------------------
def create_disclosure_payload(
    application_id: str,
    disclosure_type: str,
    expected_application_version: int,
    **overrides,
) -> dict:
    """Minimal valid Disclosure create payload (PRD §3.7).

    `expected_application_version` is mandatory per PRD §2.5 OCC.
    """
    defaults = {
        "application_id": application_id,
        "disclosure_type": disclosure_type,
        "expected_application_version": expected_application_version,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------
# UDAAPCheck
# ---------------------------------------------------------------------
def create_udaap_check_payload(
    application_id: str,
    review_outcome: str = "CLEARED",
    flagged_reasons=None,
    **overrides,
) -> dict:
    """Minimal valid UDAAPCheck create payload (PRD §3.8).

    For CLEARED, flagged_reasons MUST be omitted/empty.
    For FLAGGED, flagged_reasons MUST be a non-empty array.
    """
    payload: dict = {
        "application_id": application_id,
        "review_outcome": review_outcome,
    }
    if flagged_reasons is not None:
        payload["flagged_reasons"] = list(flagged_reasons)
    payload.update(overrides)
    return payload
