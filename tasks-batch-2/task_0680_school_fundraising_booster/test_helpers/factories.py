"""Payload factories — one per entity, input fields only.

Field names are PRD-exact. Optional fields (flat_cents, cap_cents on a pledge;
setup_buffer_minutes on a shift) are omitted from defaults so tests can exercise
both supplied and defaulted forms.
"""
from .constants import (
    DEFAULT_STARTS_AT, DEFAULT_ENDS_AT, TEST_DEFAULTS,
)


def create_campaign_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Campaign",
        "campaign_type": "CATALOG",
        "goal_cents": TEST_DEFAULTS["GOAL_CENTS"],
        "profit_split_pct": TEST_DEFAULTS["PROFIT_SPLIT_PCT"],
        "vendor_name": "Acme Vendor",
        "starts_at": DEFAULT_STARTS_AT,
        "ends_at": DEFAULT_ENDS_AT,
    }
    defaults.update(overrides)
    return defaults


def create_prize_tier_payload(campaign_id, **overrides) -> dict:
    defaults = {
        "campaign_id": campaign_id,
        "label": "T1",
        "threshold_cents": 5000,
        "prize_description": "A prize",
    }
    defaults.update(overrides)
    return defaults


def create_seller_payload(campaign_id, **overrides) -> dict:
    defaults = {
        "campaign_id": campaign_id,
        "display_name": "Test Seller",
        "guardian_email": "guardian@example.com",
    }
    defaults.update(overrides)
    return defaults


def create_product_payload(campaign_id, **overrides) -> dict:
    defaults = {
        "campaign_id": campaign_id,
        "sku": "WRAP",
        "name": "Gift Wrap",
        "unit_price_cents": TEST_DEFAULTS["UNIT_PRICE_CENTS"],
        "unit_cost_cents": TEST_DEFAULTS["UNIT_COST_CENTS"],
        "stock_qty": TEST_DEFAULTS["STOCK_QTY"],
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(campaign_id, seller_id, lines, **overrides) -> dict:
    defaults = {
        "campaign_id": campaign_id,
        "seller_id": seller_id,
        "buyer_name": "Test Buyer",
        "buyer_email": "buyer@example.com",
        "lines": lines,
    }
    defaults.update(overrides)
    return defaults


def order_line(product_id, quantity) -> dict:
    return {"product_id": product_id, "quantity": quantity}


def create_pledge_payload(campaign_id, seller_id, per_unit_cents, **overrides) -> dict:
    defaults = {
        "campaign_id": campaign_id,
        "seller_id": seller_id,
        "donor_name": "Test Donor",
        "donor_email": "donor@example.com",
        "per_unit_cents": per_unit_cents,
    }
    defaults.update(overrides)
    return defaults


def create_volunteer_payload(campaign_id, **overrides) -> dict:
    defaults = {
        "campaign_id": campaign_id,
        "full_name": "Test Volunteer",
        "email": "volunteer@example.com",
    }
    defaults.update(overrides)
    return defaults


def create_shift_payload(campaign_id, starts_at, ends_at, **overrides) -> dict:
    defaults = {
        "campaign_id": campaign_id,
        "role_label": "GRILL",
        "starts_at": starts_at,
        "ends_at": ends_at,
    }
    defaults.update(overrides)
    return defaults
