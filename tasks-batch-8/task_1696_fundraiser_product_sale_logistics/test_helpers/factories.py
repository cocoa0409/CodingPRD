"""Payload factories — one per entity, input fields only."""
from .constants import TEST_DEFAULTS


def create_campaign_payload(**overrides) -> dict:
    defaults = {
        "name": TEST_DEFAULTS["CAMPAIGN_NAME"],
        "school_name": TEST_DEFAULTS["SCHOOL_NAME"],
        "order_window_start": TEST_DEFAULTS["ORDER_WINDOW_START"],
        "order_window_end": TEST_DEFAULTS["ORDER_WINDOW_END"],
        "expected_delivery_date": TEST_DEFAULTS["EXPECTED_DELIVERY_DATE"],
        "default_profit_share_bps": TEST_DEFAULTS["DEFAULT_PROFIT_SHARE_BPS"],
    }
    defaults.update(overrides)
    return defaults


def create_group_payload(**overrides) -> dict:
    defaults = {
        "campaign_id": None,
        "name": "Group A",
    }
    defaults.update(overrides)
    return {k: v for k, v in defaults.items() if v is not None}


def create_product_payload(**overrides) -> dict:
    defaults = {
        "campaign_id": None,
        "name": "Bar",
        "sku": "BAR-01",
        "unit_price_cents": TEST_DEFAULTS["UNIT_PRICE_CENTS"],
        "supplier_unit_cost_cents": TEST_DEFAULTS["SUPPLIER_UNIT_COST_CENTS"],
        "case_pack_size": TEST_DEFAULTS["CASE_PACK_SIZE"],
    }
    defaults.update(overrides)
    return {k: v for k, v in defaults.items() if v is not None}


def create_prize_payload(**overrides) -> dict:
    defaults = {
        "campaign_id": None,
        "name": "Badge",
        "tier_type": "UNITS_SOLD",
        "threshold_value": 2,
        "prize_cost_cents": 25,
        "stock_quantity": 1,
    }
    defaults.update(overrides)
    return {k: v for k, v in defaults.items() if v is not None}


def create_seller_payload(**overrides) -> dict:
    defaults = {
        "group_id": None,
        "display_name": "Alice",
    }
    defaults.update(overrides)
    return {k: v for k, v in defaults.items() if v is not None}


def create_order_payload(**overrides) -> dict:
    defaults = {
        "seller_id": None,
        "family_contact_name": "Fam1",
        "lines": [],
    }
    defaults.update(overrides)
    return {k: v for k, v in defaults.items() if v is not None}


def create_payment_payload(**overrides) -> dict:
    defaults = {
        "order_id": None,
        "amount_cents": TEST_DEFAULTS["UNIT_PRICE_CENTS"],
        "method": "CASH",
    }
    defaults.update(overrides)
    return {k: v for k, v in defaults.items() if v is not None}


def create_supplier_order_payload(**overrides) -> dict:
    defaults = {
        "campaign_id": None,
    }
    defaults.update(overrides)
    return {k: v for k, v in defaults.items() if v is not None}


def create_distribution_event_payload(**overrides) -> dict:
    defaults = {
        "campaign_id": None,
        "venue": TEST_DEFAULTS["EVENT_VENUE"],
        "window_start": TEST_DEFAULTS["EVENT_WINDOW_START"],
        "window_end": TEST_DEFAULTS["EVENT_WINDOW_END"],
        "slot_capacity": TEST_DEFAULTS["SLOT_CAPACITY"],
    }
    defaults.update(overrides)
    return {k: v for k, v in defaults.items() if v is not None}


def create_pickup_appointment_payload(**overrides) -> dict:
    defaults = {
        "distribution_event_id": None,
        "order_id": None,
        "slot_start": "2026-09-06T15:05:00Z",
        "slot_end": "2026-09-06T15:20:00Z",
    }
    defaults.update(overrides)
    return {k: v for k, v in defaults.items() if v is not None}


def create_claim_payload(**overrides) -> dict:
    defaults = {
        "order_id": None,
        "order_line_id": None,
        "claim_type": "MISSING",
        "quantity": 1,
    }
    defaults.update(overrides)
    return {k: v for k, v in defaults.items() if v is not None}


def create_return_request_payload(**overrides) -> dict:
    defaults = {
        "seller_id": None,
        "order_id": None,
        "order_line_id": None,
        "quantity": 1,
        "reason": "UNSOLD",
    }
    defaults.update(overrides)
    return {k: v for k, v in defaults.items() if v is not None}
