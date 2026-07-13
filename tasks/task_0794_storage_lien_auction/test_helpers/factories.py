"""Payload factories — one per entity, input fields only (PRD §3, §4)."""
from .constants import CANONICAL, AUCTION_START, AUCTION_END

DEFAULTS = {
    "FACILITY_NAME": "Test Facility",
    "STATE_CODE": "TX",
    "SALES_TAX_RATE_BPS": CANONICAL["sales_tax_rate_bps"],
    "FACILITY_FEE_BPS": CANONICAL["facility_fee_bps"],
    "TENANT_NAME": "Test Tenant",
    "TENANT_EMAIL": "tenant@example.com",
    "UNIT_NUMBER": "A1",
    "MONTHLY_RENT_CENTS": CANONICAL["monthly_rent_cents"],
    "PAST_DUE_BALANCE_CENTS": CANONICAL["past_due_balance_cents"],
    "BUYER_NAME": "Test Buyer",
    "BUYER_EMAIL": "buyer@example.com",
    "RESERVE_CENTS": 50000,
    "MIN_INCREMENT_CENTS": 5000,
}


def create_facility_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["FACILITY_NAME"],
        "state_code": DEFAULTS["STATE_CODE"],
        "sales_tax_rate_bps": DEFAULTS["SALES_TAX_RATE_BPS"],
        "facility_fee_bps": DEFAULTS["FACILITY_FEE_BPS"],
    }
    defaults.update(overrides)
    return defaults


def create_tenant_payload(facility_id, **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "full_name": DEFAULTS["TENANT_NAME"],
        "email": DEFAULTS["TENANT_EMAIL"],
    }
    defaults.update(overrides)
    return defaults


def create_unit_payload(facility_id, tenant_id, **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "tenant_id": tenant_id,
        "unit_number": DEFAULTS["UNIT_NUMBER"],
        "monthly_rent_cents": DEFAULTS["MONTHLY_RENT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_lien_notice_payload(**overrides) -> dict:
    defaults = {"past_due_balance_cents": DEFAULTS["PAST_DUE_BALANCE_CENTS"]}
    defaults.update(overrides)
    return defaults


def create_buyer_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["BUYER_NAME"],
        "email": DEFAULTS["BUYER_EMAIL"],
    }
    defaults.update(overrides)
    return defaults


def fund_deposit_payload(amount_cents, **overrides) -> dict:
    defaults = {"amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults


def create_auction_payload(unit_id, **overrides) -> dict:
    defaults = {
        "unit_id": unit_id,
        "mode": "ONLINE",
        "start_at": AUCTION_START,
        "end_at": AUCTION_END,
        "reserve_cents": DEFAULTS["RESERVE_CENTS"],
        "min_increment_cents": DEFAULTS["MIN_INCREMENT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def place_bid_payload(buyer_id, amount_cents, expected_auction_version, **overrides) -> dict:
    defaults = {
        "buyer_id": buyer_id,
        "amount_cents": amount_cents,
        "expected_auction_version": expected_auction_version,
    }
    defaults.update(overrides)
    return defaults


def create_dispute_payload(subject_type, raised_by, reason="dispute reason", **overrides) -> dict:
    defaults = {
        "subject_type": subject_type,
        "raised_by": raised_by,
        "reason": reason,
    }
    defaults.update(overrides)
    return defaults


def provide_info_payload(note="info", **overrides) -> dict:
    defaults = {"note": note}
    defaults.update(overrides)
    return defaults


def resolve_dispute_payload(decision, **overrides) -> dict:
    defaults = {"decision": decision}
    defaults.update(overrides)
    return defaults
