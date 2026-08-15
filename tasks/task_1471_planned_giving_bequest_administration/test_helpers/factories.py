"""Payload factories — one per entity, input fields only.

Field names match the PRD exactly. Optional fields are omitted unless passed
through **overrides.
"""
from .constants import (
    STD_AGE,
    STD_FUNDING_MONTH,
    STD_GIFT_CENTS,
    STD_PAYOUT_BPS,
)


def create_donor_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Donor",
        "date_of_birth": "1956-03-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_rate_table_payload(**overrides) -> dict:
    defaults = {
        "label": "7520-5pct",
        "discount_rate_bps": 500,
        "effective_from": "2026-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_illustration_payload(**overrides) -> dict:
    defaults = {
        "donor_id": None,
        "vehicle_type": "CGA",
        "gift_amount_cents": STD_GIFT_CENTS,
        "payout_rate_bps": STD_PAYOUT_BPS,
        "lives": 1,
        "annuitant_1_age": STD_AGE,
        "funding_month": STD_FUNDING_MONTH,
    }
    defaults.update(overrides)
    return {k: v for k, v in defaults.items() if v is not None}


def create_gift_agreement_payload(**overrides) -> dict:
    defaults = {
        "donor_id": None,
        "vehicle_type": "CRT_ANNUITY",
        "gift_amount_cents": STD_GIFT_CENTS,
        "payout_rate_bps": 500,
        "lives": 1,
        "annuitant_1_age": STD_AGE,
        "funding_month": STD_FUNDING_MONTH,
    }
    defaults.update(overrides)
    return {k: v for k, v in defaults.items() if v is not None}


def create_designation_payload(**overrides) -> dict:
    defaults = {
        "gift_agreement_id": None,
        "slot": "PRIMARY_1",
        "beneficiary_name": "University Scholarship",
        "document_received": True,
    }
    defaults.update(overrides)
    return {k: v for k, v in defaults.items() if v is not None}


def create_gift_asset_payload(**overrides) -> dict:
    defaults = {
        "asset_kind": "CASH",
        "pledged_value_cents": STD_GIFT_CENTS,
    }
    defaults.update(overrides)
    return {k: v for k, v in defaults.items() if v is not None}


def create_estate_payload(**overrides) -> dict:
    defaults = {
        "donor_id": None,
        "notified_on": "2026-08-05T00:00:00Z",
    }
    defaults.update(overrides)
    return {k: v for k, v in defaults.items() if v is not None}


def create_probate_milestone_payload(**overrides) -> dict:
    defaults = {
        "estate_id": None,
        "kind": "PETITION",
        "due_date": "2027-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return {k: v for k, v in defaults.items() if v is not None}


def create_fund_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Scholarship Fund",
        "restriction_type": "SCHOLARSHIP",
        "gift_agreement_id": None,
    }
    defaults.update(overrides)
    return {k: v for k, v in defaults.items() if v is not None}


def create_valuation_run_payload(**overrides) -> dict:
    defaults = {
        "coverage_start": "2026-01-01T00:00:00Z",
        "coverage_end": "2026-06-30T00:00:00Z",
        "valuation_date": "2026-03-01T00:00:00Z",
    }
    defaults.update(overrides)
    return {k: v for k, v in defaults.items() if v is not None}


def create_reserve_adjustment_payload(**overrides) -> dict:
    defaults = {
        "direction": "CONTRIBUTION",
        "amount_cents": 100000,
        "expected_reserve_fund_version": None,
    }
    defaults.update(overrides)
    return {k: v for k, v in defaults.items() if v is not None}
