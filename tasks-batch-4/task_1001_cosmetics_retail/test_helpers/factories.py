"""Payload factories — one per entity, input fields only."""

import itertools

from .constants import TEST_DEFAULTS

_email_counter = itertools.count(1)


def unique_email(prefix: str = "cust") -> str:
    """Customer email is unique per customer (PRD §3.4)."""
    return f"{prefix}-{next(_email_counter)}@example.com"


def create_store_payload(**overrides) -> dict:
    payload = {
        "name": TEST_DEFAULTS["STORE_NAME"],
        "region_code": TEST_DEFAULTS["REGION_CODE"],
    }
    payload.update(overrides)
    return payload


def create_product_payload(**overrides) -> dict:
    payload = {
        "name": "Lipstick",
        "brand": TEST_DEFAULTS["BRAND"],
        "category": "MAKEUP",
        "hygiene_class": "SEALED",
        "base_price_cents": TEST_DEFAULTS["PRICE_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_variant_payload(**overrides) -> dict:
    payload = {
        "shade_name": "Rose",
        "shade_code": "RS-01",
        "finish": "SATIN",
        "undertone": "COOL",
        "depth_index": 5,
        "price_cents": TEST_DEFAULTS["PRICE_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_limited_variant_payload(**overrides) -> dict:
    """A limited-launch variant with a full launch schedule (PRD §3.1, §3.6)."""
    payload = {
        "shade_name": "Drop",
        "shade_code": "DR-01",
        "finish": "DEWY",
        "undertone": "WARM",
        "depth_index": 6,
        "price_cents": TEST_DEFAULTS["PRICE_CENTS"],
        "is_limited_launch": True,
        "launch_open_rouge_at": "2026-05-01T01:00:00Z",
        "launch_open_vib_at": "2026-05-01T02:00:00Z",
        "launch_open_public_at": "2026-05-02T00:00:00Z",
        "per_customer_cap": 2,
    }
    payload.update(overrides)
    return payload


def create_inventory_lot_payload(store_id, variant_id, **overrides) -> dict:
    payload = {
        "store_id": store_id,
        "variant_id": variant_id,
        "units_received": TEST_DEFAULTS["UNITS_RECEIVED"],
    }
    payload.update(overrides)
    return payload


def create_customer_payload(**overrides) -> dict:
    payload = {"email": unique_email(), "name": "Test Customer"}
    payload.update(overrides)
    return payload


def create_promotion_payload(**overrides) -> dict:
    payload = {"name": "Test Promotion", "promo_type": "GWP", "status": "ACTIVE"}
    payload.update(overrides)
    return payload


def create_gwp_promotion_payload(gift_variant_id, threshold_cents, **overrides) -> dict:
    payload = {
        "name": "GWP",
        "promo_type": "GWP",
        "threshold_cents": threshold_cents,
        "gift_variant_id": gift_variant_id,
        "gift_quantity": 1,
        "priority": 10,
        "status": "ACTIVE",
    }
    payload.update(overrides)
    return payload


def create_sample_promotion_payload(
    gift_variant_id, threshold_cents, **overrides
) -> dict:
    payload = {
        "name": "Sample",
        "promo_type": "SAMPLE",
        "threshold_cents": threshold_cents,
        "gift_variant_id": gift_variant_id,
        "gift_quantity": 1,
        "priority": 20,
        "status": "ACTIVE",
    }
    payload.update(overrides)
    return payload


def create_bundle_promotion_payload(
    bundle_variant_ids, bundle_discount_pct, **overrides
) -> dict:
    payload = {
        "name": "Bundle",
        "promo_type": "BUNDLE",
        "bundle_variant_ids": list(bundle_variant_ids),
        "bundle_discount_pct": bundle_discount_pct,
        "priority": 5,
        "status": "ACTIVE",
    }
    payload.update(overrides)
    return payload


def create_order_payload(customer_id, store_id, lines, **overrides) -> dict:
    """`lines` is a list of {variant_id, quantity} dicts (PRD §3.5)."""
    payload = {
        "customer_id": customer_id,
        "store_id": store_id,
        "channel": "SHIP_FROM_STORE",
        "lines": list(lines),
    }
    payload.update(overrides)
    return payload


def line(variant_id, quantity=1) -> dict:
    return {"variant_id": variant_id, "quantity": quantity}


def add_line_payload(variant_id, quantity, expected_order_version) -> dict:
    return {
        "variant_id": variant_id,
        "quantity": quantity,
        "expected_order_version": expected_order_version,
    }


def create_artist_payload(store_id, **overrides) -> dict:
    payload = {"store_id": store_id, "name": "Ada", "skills": ["BROW", "MAKEOVER"]}
    payload.update(overrides)
    return payload


def create_booking_payload(customer_id, store_id, artist_id, start_at, **overrides) -> dict:
    payload = {
        "customer_id": customer_id,
        "store_id": store_id,
        "artist_id": artist_id,
        "service_type": "BROW",
        "start_at": start_at,
    }
    payload.update(overrides)
    return payload


def create_return_request_payload(order_line_id, quantity=1, **overrides) -> dict:
    payload = {
        "order_line_id": order_line_id,
        "quantity": quantity,
        "reason": "CHANGED_MIND",
    }
    payload.update(overrides)
    return payload


def approve_decision_payload() -> dict:
    return {"decision": "APPROVE"}


def deny_decision_payload(deny_reason="OUT_OF_POLICY") -> dict:
    return {"decision": "DENY", "deny_reason": deny_reason}


def make_tester_conversion_payload(units, expected_lot_version) -> dict:
    return {"units": units, "expected_lot_version": expected_lot_version}


def shade_request_payload(undertone, depth_index, finish_pref, **overrides) -> dict:
    payload = {
        "undertone": undertone,
        "depth_index": depth_index,
        "finish_pref": finish_pref,
    }
    payload.update(overrides)
    return payload
