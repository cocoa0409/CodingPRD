"""Payload factories — one per entity, input fields only."""
import itertools

from .constants import TEST_DEFAULTS

_email_counter = itertools.count(1)


def unique_email() -> str:
    """A per-process unique email (each test starts with an empty DB)."""
    return f"buyer{next(_email_counter)}@example.com"


def create_buyer_payload(**overrides) -> dict:
    defaults = {"name": "Test Buyer", "email": unique_email()}
    defaults.update(overrides)
    return defaults


def create_event_payload(**overrides) -> dict:
    defaults = {
        "promoter_id": TEST_DEFAULTS["PROMOTER_ID"],
        "name": "Test Show",
        "venue_name": "Test Hall",
        "event_datetime": TEST_DEFAULTS["EVENT_DATETIME"],
        "hold_ttl_minutes": TEST_DEFAULTS["HOLD_TTL_MINUTES"],
        "purchase_window_minutes": TEST_DEFAULTS["PURCHASE_WINDOW_MINUTES"],
    }
    defaults.update(overrides)
    return defaults


def create_price_level_payload(**overrides) -> dict:
    defaults = {
        "name": "GA",
        "base_face_value_cents": TEST_DEFAULTS["BASE_FACE_VALUE_CENTS"],
        "is_platinum": False,
        "service_fee_pct": TEST_DEFAULTS["SERVICE_FEE_PCT"],
        "service_fee_flat_cents": TEST_DEFAULTS["SERVICE_FEE_FLAT_CENTS"],
        "dynamic_pricing_enabled": False,
    }
    defaults.update(overrides)
    return defaults


def create_seat_payload(price_level_id: str, section: str = "A", row: str = "1",
                        seat_number: str = "1", **overrides) -> dict:
    defaults = {
        "price_level_id": price_level_id,
        "section": section,
        "row": row,
        "seat_number": seat_number,
    }
    defaults.update(overrides)
    return defaults


def create_queue_token_payload(buyer_id: str, **overrides) -> dict:
    defaults = {"buyer_id": buyer_id}
    defaults.update(overrides)
    return defaults


def create_hold_payload(seat_ids, buyer_id: str, expected_event_version: int, **overrides) -> dict:
    defaults = {
        "seat_ids": list(seat_ids),
        "buyer_id": buyer_id,
        "expected_event_version": expected_event_version,
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(hold_id: str, delivery_method: str = "MOBILE", **overrides) -> dict:
    defaults = {"hold_id": hold_id, "delivery_method": delivery_method}
    defaults.update(overrides)
    return defaults


def create_refund_request_payload(reason: str, refund_destination: str,
                                  expected_order_version: int, **overrides) -> dict:
    defaults = {
        "reason": reason,
        "refund_destination": refund_destination,
        "expected_order_version": expected_order_version,
    }
    defaults.update(overrides)
    return defaults


def create_transfer_payload(ticket_id: str, to_buyer_id: str, kind: str = "GIFT", **overrides) -> dict:
    defaults = {"ticket_id": ticket_id, "to_buyer_id": to_buyer_id, "kind": kind}
    defaults.update(overrides)
    return defaults
