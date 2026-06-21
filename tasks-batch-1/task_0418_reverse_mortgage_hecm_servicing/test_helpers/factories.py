"""Payload factories — one per entity, input fields only."""
from .constants import (
    DEFAULT_HUD_LENDING_LIMIT_CENTS,
    DEFAULT_APPRAISED_VALUE_CENTS,
    DEFAULT_EXPECTED_RATE_BPS,
    DEFAULT_FACTOR_MICROS,
    DEFAULT_INITIAL_FINANCED_COSTS_CENTS,
    DEFAULT_BORROWER_BIRTHDATE,
    DEFAULT_CLOCK_ISO,
    DEFAULT_PLF_AGE,
)


def create_lender_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Servicer",
        "hud_lending_limit_cents": DEFAULT_HUD_LENDING_LIMIT_CENTS,
    }
    defaults.update(overrides)
    return defaults


def create_plf_payload(lender_id, **overrides) -> dict:
    defaults = {
        "lender_id": lender_id,
        "age": DEFAULT_PLF_AGE,
        "expected_rate_bps": DEFAULT_EXPECTED_RATE_BPS,
        "factor_micros": DEFAULT_FACTOR_MICROS,
    }
    defaults.update(overrides)
    return defaults


def set_clock_payload(lender_id, to_iso8601=DEFAULT_CLOCK_ISO, **overrides) -> dict:
    defaults = {"lender_id": lender_id, "to_iso8601": to_iso8601}
    defaults.update(overrides)
    return defaults


def create_borrower_payload(lender_id, **overrides) -> dict:
    defaults = {
        "lender_id": lender_id,
        "full_name": "Test Borrower",
        "birthdate": DEFAULT_BORROWER_BIRTHDATE,
    }
    defaults.update(overrides)
    return defaults


def create_loan_payload(lender_id, borrower_id, **overrides) -> dict:
    defaults = {
        "lender_id": lender_id,
        "borrower_id": borrower_id,
        "appraised_value_cents": DEFAULT_APPRAISED_VALUE_CENTS,
        "expected_rate_bps": DEFAULT_EXPECTED_RATE_BPS,
        "draw_type": "LINE_OF_CREDIT",
        "initial_financed_costs_cents": DEFAULT_INITIAL_FINANCED_COSTS_CENTS,
    }
    defaults.update(overrides)
    return defaults


def create_disbursement_payload(loan_id, **overrides) -> dict:
    defaults = {
        "loan_id": loan_id,
        "kind": "LINE_DRAW",
        "requested_amount_cents": 100000,
    }
    defaults.update(overrides)
    return defaults


def approve_disbursement_payload(expected_loan_version, **overrides) -> dict:
    defaults = {"expected_loan_version": expected_loan_version}
    defaults.update(overrides)
    return defaults


def create_lesa_payload(loan_id, **overrides) -> dict:
    defaults = {
        "loan_id": loan_id,
        "funding_mode": "FULLY_FUNDED",
        "annual_property_charge_cents": 600000,
        "life_expectancy_years": 10,
    }
    defaults.update(overrides)
    return defaults


def create_property_charge_payment_payload(loan_id, lesa_set_aside_id, **overrides) -> dict:
    defaults = {
        "loan_id": loan_id,
        "lesa_set_aside_id": lesa_set_aside_id,
        "charge_type": "PROPERTY_TAX",
        "coverage_start": "2024-01-01",
        "coverage_end": "2025-01-01",
        "amount_cents": 100000,
    }
    defaults.update(overrides)
    return defaults


def create_occupancy_certification_payload(loan_id, certification_year=1, **overrides) -> dict:
    defaults = {"loan_id": loan_id, "certification_year": certification_year}
    defaults.update(overrides)
    return defaults


def create_maturity_event_payload(loan_id, **overrides) -> dict:
    defaults = {
        "loan_id": loan_id,
        "event_type": "PERMANENT_VACANCY",
        "event_date": "2024-06-01",
    }
    defaults.update(overrides)
    return defaults


def create_nbs_deferral_payload(loan_id, borrower_id, maturity_event_id, **overrides) -> dict:
    defaults = {
        "loan_id": loan_id,
        "borrower_id": borrower_id,
        "maturity_event_id": maturity_event_id,
    }
    defaults.update(overrides)
    return defaults


def create_resolution_payload(loan_id, path="PAYOFF", **overrides) -> dict:
    defaults = {"loan_id": loan_id, "path": path}
    defaults.update(overrides)
    return defaults


def post_accrual_payload(number_of_months, **overrides) -> dict:
    defaults = {"number_of_months": number_of_months}
    defaults.update(overrides)
    return defaults
