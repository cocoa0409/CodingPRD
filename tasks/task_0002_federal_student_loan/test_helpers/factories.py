"""Payload factories — one per entity, input fields only."""


def create_borrower_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Borrower",
        "ssn_last4": "1234",
        "is_veteran": False,
    }
    defaults.update(overrides)
    return defaults


def create_loan_payload(borrower_id: str, **overrides) -> dict:
    defaults = {
        "borrower_id": borrower_id,
        "loan_type": "DIRECT_UNSUB",
        "principal_cents": 1_000_000,
        "interest_rate_bps": 500,
        "disbursement_date": "2026-06-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_repayment_plan_payload(loan_id: str, expected_loan_version: int,
                                  **overrides) -> dict:
    defaults = {
        "loan_id": loan_id,
        "plan_type": "STANDARD",
        "effective_date": "2026-06-01T00:00:00Z",
        "expected_loan_version": expected_loan_version,
    }
    defaults.update(overrides)
    return defaults


def create_income_certification_payload(borrower_id: str, **overrides) -> dict:
    defaults = {
        "borrower_id": borrower_id,
        "agi_cents": 6_000_000,
        "family_size": 2,
        "state_code": "CA",
        "effective_date": "2026-05-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_qualifying_employment_payload(borrower_id: str, **overrides) -> dict:
    defaults = {
        "borrower_id": borrower_id,
        "employer_name": "Test Employer",
        "employer_type": "GOVERNMENT",
        "period_start": "2025-01-01T00:00:00Z",
        "period_end": "2027-12-31T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(loan_id: str, **overrides) -> dict:
    defaults = {
        "loan_id": loan_id,
        "amount_cents": 10_000,
        "payment_date": "2026-06-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_discharge_application_payload(loan_id: str, **overrides) -> dict:
    defaults = {
        "loan_id": loan_id,
        "discharge_type": "VETERAN_TOTAL_DISABILITY",
    }
    defaults.update(overrides)
    return defaults
