"""Payload factories — one per entity, input fields only.

Defaults reflect the canonical balcony scenario used throughout the design
indices (base fare 119900, 7-night Aurora sailing). Override per test.
"""
from .constants import TEST_DEFAULTS


def create_sailing_payload(**overrides) -> dict:
    payload = {
        "ship_name": "Aurora",
        "itinerary_code": "WCAR7N",
        "embark_date": TEST_DEFAULTS["EMBARK_DATE"],
        "disembark_date": TEST_DEFAULTS["DISEMBARK_DATE"],
        "nights": TEST_DEFAULTS["NIGHTS"],
    }
    payload.update(overrides)
    return payload


def create_cabin_category_payload(sailing_id, **overrides) -> dict:
    payload = {
        "sailing_id": sailing_id,
        "code": "BALCONY",
        "deck_low": 8,
        "deck_high": 10,
        "base_fare_per_guest_cents": TEST_DEFAULTS["BALCONY_BASE_FARE_CENTS"],
        "max_occupancy": 4,
    }
    payload.update(overrides)
    return payload


def create_cabin_payload(cabin_category_id, cabin_number, deck=8, **overrides) -> dict:
    payload = {
        "cabin_category_id": cabin_category_id,
        "cabin_number": cabin_number,
        "deck": deck,
    }
    payload.update(overrides)
    return payload


def create_group_block_payload(sailing_id, cabin_category_id, **overrides) -> dict:
    payload = {
        "sailing_id": sailing_id,
        "group_name": "Reunion",
        "cabin_category_id": cabin_category_id,
        "block_size": 2,
        "group_discount_pct": 0.15,
        "release_cutoff_date": "2026-08-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_booking_payload(sailing_id, cabin_category_id, owner_user_id,
                           expected_sailing_version, **overrides) -> dict:
    payload = {
        "sailing_id": sailing_id,
        "cabin_category_id": cabin_category_id,
        "owner_user_id": owner_user_id,
        "expected_sailing_version": expected_sailing_version,
    }
    payload.update(overrides)
    return payload


def create_guest_payload(booking_id, full_name="C One", age=40, **overrides) -> dict:
    payload = {
        "booking_id": booking_id,
        "full_name": full_name,
        "age": age,
    }
    payload.update(overrides)
    return payload


def create_add_on_payload(booking_id, kind, title, price_cents, **overrides) -> dict:
    payload = {
        "booking_id": booking_id,
        "kind": kind,
        "title": title,
        "price_cents": price_cents,
    }
    payload.update(overrides)
    return payload


def create_dining_reservation_payload(booking_id, venue_code, seating_start,
                                      party_size, **overrides) -> dict:
    payload = {
        "booking_id": booking_id,
        "venue_code": venue_code,
        "seating_start": seating_start,
        "party_size": party_size,
    }
    payload.update(overrides)
    return payload


def create_payment_payload(booking_id, kind, amount_cents, **overrides) -> dict:
    payload = {
        "booking_id": booking_id,
        "kind": kind,
        "amount_cents": amount_cents,
    }
    payload.update(overrides)
    return payload


def create_folio_charge_payload(description, amount_cents, **overrides) -> dict:
    payload = {
        "description": description,
        "amount_cents": amount_cents,
    }
    payload.update(overrides)
    return payload
