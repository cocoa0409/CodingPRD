"""Payload factories — one per entity, input fields only."""
from .constants import TEST_DEFAULTS


def create_basic_plan_payload(**overrides) -> dict:
    """BASIC plan: no reward (rate/cap must be 0)."""
    defaults = {
        "tier": "BASIC",
        "annual_fee_cents": TEST_DEFAULTS["BASIC_ANNUAL_FEE"],
        "max_household_cards": TEST_DEFAULTS["MAX_HOUSEHOLD_CARDS"],
        "addon_fee_cents": TEST_DEFAULTS["BASIC_ADDON_FEE"],
    }
    defaults.update(overrides)
    return defaults


def create_executive_plan_payload(**overrides) -> dict:
    """EXECUTIVE plan with reward accrual."""
    defaults = {
        "tier": "EXECUTIVE",
        "annual_fee_cents": TEST_DEFAULTS["EXEC_ANNUAL_FEE"],
        "reward_rate_bps": TEST_DEFAULTS["EXEC_REWARD_RATE_BPS"],
        "reward_cap_cents": TEST_DEFAULTS["EXEC_REWARD_CAP"],
        "max_household_cards": TEST_DEFAULTS["MAX_HOUSEHOLD_CARDS"],
        "addon_fee_cents": TEST_DEFAULTS["EXEC_ADDON_FEE"],
    }
    defaults.update(overrides)
    return defaults


def create_membership_payload(plan_id, **overrides) -> dict:
    defaults = {
        "plan_id": plan_id,
        "primary_member_name": "Test Member",
    }
    defaults.update(overrides)
    return defaults


def create_product_payload(sku, **overrides) -> dict:
    defaults = {
        "sku": sku,
        "list_price_cents": TEST_DEFAULTS["LIST_PRICE"],
        "member_price_cents": TEST_DEFAULTS["MEMBER_PRICE"],
    }
    defaults.update(overrides)
    return defaults


def create_instant_saving_payload(product_id, **overrides) -> dict:
    defaults = {
        "product_id": product_id,
        "kind": "INSTANT_SAVINGS",
        "amount_cents": 1000,
        "window_start_utc": "2026-01-01T00:00:00Z",
        "window_end_utc": "2026-12-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(membership_id, **overrides) -> dict:
    defaults = {
        "membership_id": membership_id,
        "purpose": "SIGNUP",
        "outcome": "SUCCEEDED",
    }
    defaults.update(overrides)
    return defaults


def create_household_card_payload(membership_id, **overrides) -> dict:
    defaults = {
        "membership_id": membership_id,
        "cardholder_name": "Test Cardholder",
        "card_kind": "INCLUDED",
    }
    defaults.update(overrides)
    return defaults


def create_line_payload(product_id, qty=1, **overrides) -> dict:
    defaults = {"product_id": product_id, "qty": qty}
    defaults.update(overrides)
    return defaults


def create_return_payload(membership_id, product_id, qty=1, **overrides) -> dict:
    defaults = {
        "membership_id": membership_id,
        "product_id": product_id,
        "qty": qty,
    }
    defaults.update(overrides)
    return defaults
