"""Payload factories — one per entity, input fields only."""
from .constants import TEST_DEFAULTS


def create_fan_payload(**overrides) -> dict:
    defaults = {
        "email": "fan@x.com",
        "full_name": "Test Fan",
        "device_fingerprint": "dev-test",
    }
    defaults.update(overrides)
    return defaults


def create_event_payload(**overrides) -> dict:
    defaults = {
        "title": "Test Event",
        "venue_capacity": TEST_DEFAULTS["VENUE_CAPACITY"],
        "presale_code": TEST_DEFAULTS["PRESALE_CODE"],
        "face_value_cents": TEST_DEFAULTS["FACE_VALUE_CENTS"],
        "resale_cap_pct": TEST_DEFAULTS["RESALE_CAP_PCT"],
    }
    defaults.update(overrides)
    return defaults


def create_price_tier_payload(event_id: str, **overrides) -> dict:
    defaults = {
        "event_id": event_id,
        "name": "FLOOR",
        "allocation": TEST_DEFAULTS["TIER_ALLOCATION"],
        "base_multiplier_bps": TEST_DEFAULTS["BASE_MULTIPLIER_BPS"],
    }
    defaults.update(overrides)
    return defaults


def create_queue_entry_payload(event_id: str, fan_id: str, tier_id: str, **overrides) -> dict:
    defaults = {
        "event_id": event_id,
        "fan_id": fan_id,
        "tier_id": tier_id,
        "presale_code_used": TEST_DEFAULTS["PRESALE_CODE"],
        "requested_qty": 1,
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(queue_entry_id: str, fan_id: str, tier_id: str, **overrides) -> dict:
    defaults = {
        "queue_entry_id": queue_entry_id,
        "fan_id": fan_id,
        "tier_id": tier_id,
        "quantity": 1,
    }
    defaults.update(overrides)
    return defaults


def create_transfer_payload(ticket_id: str, sender_fan_id: str, recipient_fan_id: str, **overrides) -> dict:
    defaults = {
        "ticket_id": ticket_id,
        "sender_fan_id": sender_fan_id,
        "recipient_fan_id": recipient_fan_id,
    }
    defaults.update(overrides)
    return defaults


def create_resale_listing_payload(ticket_id: str, seller_fan_id: str, list_price_cents: int, **overrides) -> dict:
    defaults = {
        "ticket_id": ticket_id,
        "seller_fan_id": seller_fan_id,
        "list_price_cents": list_price_cents,
    }
    defaults.update(overrides)
    return defaults
