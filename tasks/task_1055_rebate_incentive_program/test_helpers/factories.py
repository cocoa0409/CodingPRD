"""Payload factories — one per entity, input fields only."""

import itertools

from .constants import TEST_DEFAULTS

_serial_counter = itertools.count(1)


def next_serial(prefix: str = "SN") -> str:
    """Unique manufacturer serial number for a receipt."""
    return f"{prefix}-{next(_serial_counter):06d}"


def create_program_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Rebate Program",
        "budget_total_cents": TEST_DEFAULTS["BUDGET_TOTAL_CENTS"],
        "fiscal_year": TEST_DEFAULTS["FISCAL_YEAR"],
        "escheat_jurisdiction": TEST_DEFAULTS["ESCHEAT_JURISDICTION"],
    }
    defaults.update(overrides)
    return defaults


def create_offer_payload(program_id: str, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "name": "Test Offer",
        "channel": "DEALER",
        "sku_scope": TEST_DEFAULTS["DEALER_SKU_SCOPE"],
        "effective_start_date": TEST_DEFAULTS["OFFER_START"],
        "effective_end_date": TEST_DEFAULTS["OFFER_END"],
        "max_rebate_cents_per_claim": TEST_DEFAULTS["MAX_REBATE_CENTS_PER_CLAIM"],
    }
    defaults.update(overrides)
    return defaults


def create_claimant_payload(**overrides) -> dict:
    defaults = {
        "type": "DEALER",
        "legal_name": "Test Dealer LLC",
        "email": "ap@testdealer.example",
        "mailing_state": TEST_DEFAULTS["DEALER_MAILING_STATE"],
    }
    defaults.update(overrides)
    return defaults


def create_claim_payload(offer_id: str, claimant_id: str, **overrides) -> dict:
    defaults = {"offer_id": offer_id, "claimant_id": claimant_id}
    defaults.update(overrides)
    return defaults


def receipt_line(sku: str = "TOOLS-A", quantity: int = 10, unit_price_cents: int = 2000) -> dict:
    return {"sku": sku, "quantity": quantity, "unit_price_cents": unit_price_cents}


def create_receipt_payload(**overrides) -> dict:
    defaults = {
        "serial_number": next_serial(),
        "purchase_date": TEST_DEFAULTS["PURCHASE_DATE"],
        "retailer_name": TEST_DEFAULTS["RETAILER_DEALER"],
        "lines": [receipt_line()],
    }
    defaults.update(overrides)
    return defaults


def create_payout_payload(expected_claim_version: int, **overrides) -> dict:
    defaults = {"expected_claim_version": expected_claim_version}
    defaults.update(overrides)
    return defaults


def create_budget_adjustment_payload(
    delta_cents: int, expected_program_version: int, **overrides
) -> dict:
    defaults = {
        "delta_cents": delta_cents,
        "memo": "Budget adjustment",
        "expected_program_version": expected_program_version,
    }
    defaults.update(overrides)
    return defaults


def create_fraud_case_payload(claimant_id: str, **overrides) -> dict:
    defaults = {"claimant_id": claimant_id, "opened_reason": "MANUAL_AUDIT"}
    defaults.update(overrides)
    return defaults
