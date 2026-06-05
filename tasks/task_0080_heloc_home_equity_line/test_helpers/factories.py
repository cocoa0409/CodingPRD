"""Payload factories — one per entity, input fields only."""
from .constants import (
    DEFAULT_MARGIN_BPS,
    DEFAULT_RATE_CEILING_BPS,
    DEFAULT_CREDIT_LIMIT_CENTS,
    DEFAULT_APPRAISED_VALUE_CENTS,
    DEFAULT_ANNUAL_INCOME_CENTS,
    DEFAULT_PRIME_RATE_BPS,
)


def create_borrower_payload(**overrides) -> dict:
    """Borrower input fields: full_name, annual_income_cents, monthly_debt_obligation_cents?,
    credit_score, kyc_status?."""
    defaults = {
        "full_name": "Test Borrower",
        "annual_income_cents": DEFAULT_ANNUAL_INCOME_CENTS,
        "monthly_debt_obligation_cents": 100000,
        "credit_score": 750,
        "kyc_status": "CLEARED",
    }
    defaults.update(overrides)
    return defaults


def create_property_payload(**overrides) -> dict:
    """Property input fields: street_address, appraised_value_cents,
    senior_lien_balance_cents?, county_fips."""
    defaults = {
        "street_address": "1 Main St",
        "appraised_value_cents": DEFAULT_APPRAISED_VALUE_CENTS,
        "senior_lien_balance_cents": 0,
        "county_fips": "06037",
    }
    defaults.update(overrides)
    return defaults


def create_index_rate_payload(**overrides) -> dict:
    """IndexRate input fields: index_name?, rate_bps, effective_date."""
    defaults = {
        "index_name": "PRIME",
        "rate_bps": DEFAULT_PRIME_RATE_BPS,
        "effective_date": "2026-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def supersede_index_rate_payload(rate_bps, effective_date, expected_indexrate_version, **overrides) -> dict:
    """Supersede input fields: rate_bps, effective_date, expected_indexrate_version."""
    defaults = {
        "rate_bps": rate_bps,
        "effective_date": effective_date,
        "expected_indexrate_version": expected_indexrate_version,
    }
    defaults.update(overrides)
    return defaults


def create_heloc_payload(borrower_id, property_id, **overrides) -> dict:
    """Heloc input fields: borrower_id, property_id, lien_position, credit_limit_cents,
    margin_bps, rate_ceiling_bps, annual_fee_cents?, origination_date, draw_period_years?,
    repayment_period_years?."""
    defaults = {
        "borrower_id": borrower_id,
        "property_id": property_id,
        "lien_position": "FIRST",
        "credit_limit_cents": DEFAULT_CREDIT_LIMIT_CENTS,
        "margin_bps": DEFAULT_MARGIN_BPS,
        "rate_ceiling_bps": DEFAULT_RATE_CEILING_BPS,
        "origination_date": "2026-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_covenant_payload(covenant_type, threshold_value, **overrides) -> dict:
    """Covenant input fields: covenant_type, threshold_value."""
    defaults = {
        "covenant_type": covenant_type,
        "threshold_value": threshold_value,
    }
    defaults.update(overrides)
    return defaults


def create_draw_payload(amount_cents, **overrides) -> dict:
    """Draw input fields: amount_cents."""
    defaults = {"amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults


def create_payment_payload(amount_cents, **overrides) -> dict:
    """Payment input fields: amount_cents."""
    defaults = {"amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults


def declare_default_payload(covenant_id, **overrides) -> dict:
    """Declare-default input fields: covenant_id."""
    defaults = {"covenant_id": covenant_id}
    defaults.update(overrides)
    return defaults


def clock_payload(to_iso8601) -> dict:
    return {"to_iso8601": to_iso8601}
