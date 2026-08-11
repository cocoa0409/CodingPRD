"""Payload factories — one per entity, input fields only."""

from .constants import STD_CARD, TEST_DEFAULTS


def create_client_payload(**overrides) -> dict:
    defaults = dict(TEST_DEFAULTS["CLIENT"])
    defaults.update(overrides)
    return defaults


def create_family_member_payload(client_id, **overrides) -> dict:
    defaults = {
        "client_id": client_id,
        "full_name": "Faye F",
        "relation": "daughter",
        "access_level": "BILLING_PAYER",
    }
    defaults.update(overrides)
    return defaults


def create_driver_payload(**overrides) -> dict:
    defaults = dict(TEST_DEFAULTS["DRIVER"])
    defaults.update(overrides)
    return defaults


def create_compliance_doc_payload(driver_id, doc_type, **overrides) -> dict:
    defaults = {
        "driver_id": driver_id,
        "doc_type": doc_type,
        "valid_from": TEST_DEFAULTS["DOC_VALID_FROM"],
        "valid_until": TEST_DEFAULTS["DOC_VALID_UNTIL"],
    }
    defaults.update(overrides)
    return defaults


def create_rate_card_payload(**overrides) -> dict:
    defaults = dict(STD_CARD)
    defaults.update(overrides)
    return defaults


def create_standing_ride_payload(client_id, **overrides) -> dict:
    defaults = {
        "client_id": client_id,
        "weekday": "MON",
        "pickup_time_of_day_minutes": 540,
        "kind": "GROCERY",
        "estimated_duration_minutes": 60,
        "estimated_distance_miles": 10,
        "origin_zone": "north",
        "starts_on": "2026-06-01",
        "ends_on": "2026-07-31",
    }
    defaults.update(overrides)
    return defaults


def create_ride_payload(client_id, **overrides) -> dict:
    defaults = {
        "client_id": client_id,
        "kind": "GROCERY",
        "scheduled_pickup_at": "2026-06-01T10:00:00Z",
        "estimated_duration_minutes": 60,
        "estimated_distance_miles": 10,
        "origin_zone": "north",
    }
    defaults.update(overrides)
    return defaults


def create_invoice_payload(client_id, **overrides) -> dict:
    defaults = {
        "client_id": client_id,
        "period_start": "2026-06-01",
        "period_end": "2026-06-08",
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(client_id, **overrides) -> dict:
    defaults = {
        "client_id": client_id,
        "amount_cents": 1000,
        "method": "CARD",
    }
    defaults.update(overrides)
    return defaults
