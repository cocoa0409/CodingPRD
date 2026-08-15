"""Payload factories — one per creatable entity, input fields only (PRD §3, §4)."""
from .constants import DEFAULTS


def create_borrower_payload(**overrides) -> dict:
    defaults = {
        "legal_name": "Test Borrower",
        "sector": "INDUSTRIAL",
        "risk_rating": "CROSSOVER",
    }
    defaults.update(overrides)
    return defaults


def create_facility_payload(borrower_id, **overrides) -> dict:
    defaults = {
        "borrower_id": borrower_id,
        "facility_name": "Test Facility",
        "total_commitment_cents": 10_000_000,
        "currency": DEFAULTS["CURRENCY"],
        "interest_rate_bps": DEFAULTS["INTEREST_RATE_BPS"],
        "day_count_basis": "ACT_360",
        "servicing_fee_bps": DEFAULTS["SERVICING_FEE_BPS"],
        "default_interest_addon_bps": DEFAULTS["DEFAULT_INTEREST_ADDON_BPS"],
        "maturity_date": DEFAULTS["MATURITY_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_participant_payload(facility_id, **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "participant_name": "Test Participant",
        "commitment_cents": 1_000_000,
    }
    defaults.update(overrides)
    return defaults


def create_draw_payload(facility_id, expected_facility_version, **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "draw_amount_cents": 1_000_000,
        "accrual_start_date": DEFAULTS["DRAW_START"],
        "accrual_end_date": DEFAULTS["DRAW_END"],
        "expected_facility_version": expected_facility_version,
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(facility_id, **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "payment_type": "REGULAR",
        "amount_cents": 100_000,
        "value_date": "2026-08-31",
    }
    defaults.update(overrides)
    return defaults


def create_modification_payload(facility_id, modification_type, terms, **overrides) -> dict:
    payload = {
        "facility_id": facility_id,
        "modification_type": modification_type,
        "terms": terms,
    }
    payload.update(overrides)
    return payload


def create_default_case_payload(facility_id, **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "default_type": "PAYMENT_DEFAULT",
    }
    defaults.update(overrides)
    return defaults


def create_statement_payload(facility_id, **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "statement_type": "QUARTERLY",
        "period_end_date": "2026-06-30",
        "document_ref": "s3://docs/statement.pdf",
    }
    defaults.update(overrides)
    return defaults


def create_package_payload(facility_id, **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "period_label": "2026-06",
        "period_start_date": "2026-06-01",
        "period_end_date": "2026-06-30",
        "due_date": "2026-08-15",
    }
    defaults.update(overrides)
    return defaults


def create_transfer_payload(facility_id, **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "transfer_amount_cents": 1_000_000,
        "settlement_date": "2026-08-20",
        "transferee_name": "Transferee Bank",
    }
    defaults.update(overrides)
    return defaults


def create_buyback_demand_payload(facility_id, **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "breach_type": "MISREPRESENTATION",
    }
    defaults.update(overrides)
    return defaults
