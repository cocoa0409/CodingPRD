"""Payload factories — one per entity, input fields only."""
from .constants import TEST_DEFAULTS


def create_customer_payload(**overrides) -> dict:
    defaults = {"legal_name": "Test Customer", "email": "customer@example.com"}
    defaults.update(overrides)
    return defaults


def create_application_payload(customer_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "annual_income_cents": TEST_DEFAULTS["ANNUAL_INCOME_CENTS"],
        "liquid_net_worth_cents": TEST_DEFAULTS["LIQUID_NET_WORTH_CENTS"],
        "investment_experience_years": TEST_DEFAULTS["EXPERIENCE_YEARS"],
    }
    defaults.update(overrides)
    return defaults


def create_security_profile_payload(**overrides) -> dict:
    defaults = {
        "symbol": "ABC",
        "marginable": True,
        "house_maint_long_bps": TEST_DEFAULTS["HOUSE_MAINT_LONG_BPS"],
        "house_maint_short_bps": TEST_DEFAULTS["HOUSE_MAINT_SHORT_BPS"],
        "liquidity_tier": TEST_DEFAULTS["LIQUIDITY_TIER"],
        "concentration_threshold_bps": TEST_DEFAULTS["CONCENTRATION_THRESHOLD_BPS"],
    }
    defaults.update(overrides)
    return defaults


def create_market_mark_payload(security_id, **overrides) -> dict:
    defaults = {
        "security_id": security_id,
        "mark_type": "REALTIME",
        "price_cents": TEST_DEFAULTS["MARK_PRICE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(security_id, **overrides) -> dict:
    defaults = {"security_id": security_id, "side": "BUY", "quantity": 1}
    defaults.update(overrides)
    return defaults


def create_cash_movement_payload(expected_account_version, **overrides) -> dict:
    defaults = {
        "movement_type": "DEPOSIT",
        "amount_cents": 100_000,
        "expected_account_version": expected_account_version,
    }
    defaults.update(overrides)
    return defaults


def create_liquidation_order_payload(call_id, expected_account_version, **overrides) -> dict:
    defaults = {
        "call_id": call_id,
        "expected_account_version": expected_account_version,
    }
    defaults.update(overrides)
    return defaults


def create_liquidation_fill_payload(**overrides) -> dict:
    defaults = {"filled_quantity": 1, "fill_price_cents": TEST_DEFAULTS["MARK_PRICE_CENTS"]}
    defaults.update(overrides)
    return defaults


def create_rate_tier_payload(**overrides) -> dict:
    defaults = {
        "tier_level": 1,
        "min_balance_cents": 0,
        "annual_rate_bps": 1200,
        "effective_from": "2026-01-01",
        "effective_to": None,
    }
    defaults.update(overrides)
    return defaults


def create_dispute_payload(call_id, **overrides) -> dict:
    defaults = {"call_id": call_id, "reason": "Dispute reason"}
    defaults.update(overrides)
    return defaults
