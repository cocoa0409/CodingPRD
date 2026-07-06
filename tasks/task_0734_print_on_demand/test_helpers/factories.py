"""Payload factories — one per entity, input fields only."""
from .constants import TEST_DEFAULTS


def creator_register_payload(**overrides) -> dict:
    defaults = {
        "email": "creator@example.com",
        "display_name": "Test Creator",
        "payout_country_code": "US",
    }
    defaults.update(overrides)
    return defaults


def creator_verify_payload(**overrides) -> dict:
    defaults = {"outcome": "VERIFIED"}
    defaults.update(overrides)
    return defaults


def storefront_payload(creator_id: str, **overrides) -> dict:
    defaults = {
        "creator_id": creator_id,
        "slug": "test-storefront",
        "integration_channel": "NATIVE",
        "markup_bps": TEST_DEFAULTS["MARKUP_BPS"],
    }
    defaults.update(overrides)
    return defaults


def storefront_update_payload(**overrides) -> dict:
    defaults = {"markup_bps": TEST_DEFAULTS["MARKUP_BPS"]}
    defaults.update(overrides)
    return defaults


def link_channel_payload(expected_storefront_version: int, **overrides) -> dict:
    defaults = {"expected_storefront_version": expected_storefront_version}
    defaults.update(overrides)
    return defaults


def product_payload(**overrides) -> dict:
    defaults = {
        "sku": "T-DEFAULT",
        "category": "APPAREL",
        "base_cost_cents": TEST_DEFAULTS["PRODUCT_BASE_COST_CENTS"],
        "dimensions_json": dict(TEST_DEFAULTS["DIMENSIONS_JSON"]),
    }
    defaults.update(overrides)
    return defaults


def variant_payload(**overrides) -> dict:
    defaults = {"color": "BLACK", "size": "M"}
    defaults.update(overrides)
    return defaults


def design_payload(**overrides) -> dict:
    defaults = {"file_hash": "hash_default_1"}
    defaults.update(overrides)
    return defaults


def listing_payload(storefront_id: str, design_id: str, variant_id: str, **overrides) -> dict:
    defaults = {
        "storefront_id": storefront_id,
        "design_id": design_id,
        "variant_id": variant_id,
        "title": "Test Listing",
    }
    defaults.update(overrides)
    return defaults


def order_payload(storefront_id: str, listing_id: str, **overrides) -> dict:
    defaults = {
        "storefront_id": storefront_id,
        "listing_id": listing_id,
        "buyer_email": "buyer@example.com",
        "ship_country_code": "US",
        "item_count": 1,
        "is_sample": False,
    }
    defaults.update(overrides)
    return defaults


def refund_payload(refund_amount_cents: int) -> dict:
    return {"refund_amount_cents": refund_amount_cents}


def fulfillment_partner_payload(**overrides) -> dict:
    defaults = {
        "name": "US Print A",
        "country_code": "US",
        "cost_multiplier_bps": TEST_DEFAULTS["PARTNER_COST_MULTIPLIER_BPS"],
        "max_backlog_hours": TEST_DEFAULTS["PARTNER_MAX_BACKLOG_HOURS"],
    }
    defaults.update(overrides)
    return defaults


def reprint_request_payload(**overrides) -> dict:
    defaults = {"fault_category": "CONSUMER_FAULT", "reason_code": "DAMAGED"}
    defaults.update(overrides)
    return defaults


def payout_cycle_payload(cycle_start: str, cycle_end: str) -> dict:
    return {"cycle_start": cycle_start, "cycle_end": cycle_end}


def clock_set_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}


def ingest_channel_order_payload(
    channel: str,
    external_ref: str,
    listing_id: str,
    **overrides,
) -> dict:
    defaults = {
        "channel": channel,
        "external_ref": external_ref,
        "listing_id": listing_id,
        "buyer_email": "channel_buyer@example.com",
        "ship_country_code": "US",
        "item_count": 1,
    }
    defaults.update(overrides)
    return defaults
