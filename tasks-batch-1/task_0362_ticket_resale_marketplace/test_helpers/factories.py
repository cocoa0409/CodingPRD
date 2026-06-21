"""Payload factories — one per entity, input fields only (PRD §3, §4)."""
import itertools

from .constants import (
    CANON_FACE_VALUE_CENTS,
    CANON_CAP_MULTIPLIER,
    CANON_ASK_PRICE_CENTS,
)

# Monotonic counter so factory-defaulted barcode tokens never collide within a
# test (barcode_token must be globally unique across non-VOID seats, PRD §3.3).
_barcode_counter = itertools.count(1)


def unique_barcode(prefix: str = "BC") -> str:
    return f"{prefix}-{next(_barcode_counter)}"


def create_venue_payload(**overrides) -> dict:
    payload = {"name": "Test Arena", "timezone": "UTC"}
    payload.update(overrides)
    return payload


def create_section_payload(venue_id, **overrides) -> dict:
    payload = {
        "venue_id": venue_id,
        "name": "FLOOR-A",
        "price_zone": "STANDARD",
        "face_value_cents": CANON_FACE_VALUE_CENTS,
        "row_count": 1,
        "seats_per_row": 1,
    }
    payload.update(overrides)
    return payload


def create_event_payload(venue_id, **overrides) -> dict:
    payload = {
        "venue_id": venue_id,
        "title": "Test Show",
        "doors_open_at": "2026-09-01T19:00:00.000Z",
        "price_cap_multiplier": CANON_CAP_MULTIPLIER,
    }
    payload.update(overrides)
    return payload


def create_seller_payload(**overrides) -> dict:
    payload = {"display_name": "Test Seller", "payout_account_ref": "acct_test"}
    payload.update(overrides)
    return payload


def create_buyer_payload(**overrides) -> dict:
    payload = {"display_name": "Test Buyer"}
    payload.update(overrides)
    return payload


def create_listing_payload(event_id, seller_id, section_id, **overrides) -> dict:
    payload = {
        "event_id": event_id,
        "seller_id": seller_id,
        "section_id": section_id,
        "delivery_method": "MOBILE_TRANSFER",
        "ask_price_cents": CANON_ASK_PRICE_CENTS,
        "pricing_mode": "FIXED",
        "split_rule": "ANY",
    }
    payload.update(overrides)
    return payload


def create_seat_payload(listing_id, **overrides) -> dict:
    payload = {
        "listing_id": listing_id,
        "row_label": "1",
        "seat_number": 1,
        "barcode_token": unique_barcode(),
    }
    payload.update(overrides)
    return payload


def create_order_payload(listing_id, buyer_id, expected_listing_version, **overrides) -> dict:
    payload = {
        "listing_id": listing_id,
        "buyer_id": buyer_id,
        "quantity": 1,
        "expected_listing_version": expected_listing_version,
    }
    payload.update(overrides)
    return payload


def create_guarantee_claim_payload(order_id, reason="NOT_DELIVERED", **overrides) -> dict:
    payload = {"order_id": order_id, "reason": reason}
    payload.update(overrides)
    return payload


def create_fraud_flag_payload(subject_type, signal, **overrides) -> dict:
    payload = {"subject_type": subject_type, "signal": signal}
    payload.update(overrides)
    return payload


def set_trust_tier_payload(trust_tier, **overrides) -> dict:
    payload = {"trust_tier": trust_tier}
    payload.update(overrides)
    return payload
