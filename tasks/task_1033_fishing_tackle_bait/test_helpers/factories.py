"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "CUSTOMER_STATE": "CA",
    "ADULT_BIRTH_DATE": "1985-01-01",
}


def customer_payload(**overrides) -> dict:
    payload = {
        "name": "Test Angler",
        "email": "angler@example.com",
        "state_code": DEFAULTS["CUSTOMER_STATE"],
        "birth_date": DEFAULTS["ADULT_BIRTH_DATE"],
    }
    payload.update(overrides)
    return payload


def product_payload(**overrides) -> dict:
    payload = {
        "sku": "SKU-DEFAULT",
        "name": "Test Product",
        "category": "TERMINAL_TACKLE",
        "unit_price_cents": 1000,
        "stock_qty": 100,
    }
    payload.update(overrides)
    return payload


def license_payload(**overrides) -> dict:
    payload = {
        "customer_id": None,
        "license_type": "RESIDENT_ANNUAL",
        "state_code": DEFAULTS["CUSTOMER_STATE"],
        "valid_from": "2026-07-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def bait_tank_payload(**overrides) -> dict:
    payload = {
        "name": "Test Tank",
        "species": "MINNOW",
        "capacity_units": 100,
        "mortality_rate_bps_per_day": 0,
    }
    payload.update(overrides)
    return payload


def batch_payload(**overrides) -> dict:
    payload = {
        "initial_count": 50,
        "expected_bait_tank_version": 1,
    }
    payload.update(overrides)
    return payload


def guide_payload(**overrides) -> dict:
    payload = {
        "name": "Test Guide",
        "guide_license_no": "G-DEFAULT",
        "half_day_rate_cents": 25000,
        "full_day_rate_cents": 45000,
        "per_extra_angler_cents": 5000,
        "max_party_size": 6,
    }
    payload.update(overrides)
    return payload


def venue_payload(**overrides) -> dict:
    payload = {
        "name": "Test Venue",
        "water_type": "LAKE",
    }
    payload.update(overrides)
    return payload


def charter_booking_payload(**overrides) -> dict:
    payload = {
        "customer_id": None,
        "guide_id": None,
        "venue_id": None,
        "trip_type": "HALF_DAY",
        "party_size": 2,
        "start_at": "2026-07-10T08:00:00Z",
        "end_at": "2026-07-10T12:00:00Z",
    }
    payload.update(overrides)
    return payload


def tournament_payload(**overrides) -> dict:
    payload = {
        "venue_id": None,
        "name": "Test Tournament",
        "entry_fee_cents": 2000,
        "registration_open_at": "2026-07-01T00:00:00Z",
        "registration_close_at": "2026-08-01T00:00:00Z",
        "start_at": "2026-09-05T06:00:00Z",
        "end_at": "2026-09-05T18:00:00Z",
        "max_entries": 20,
        "prize_points": 500,
    }
    payload.update(overrides)
    return payload


def tournament_entry_payload(**overrides) -> dict:
    payload = {"customer_id": None}
    payload.update(overrides)
    return payload


def weigh_in_payload(**overrides) -> dict:
    payload = {
        "species": "LARGEMOUTH_BASS",
        "weight_grams": 3000,
    }
    payload.update(overrides)
    return payload


def service_order_payload(**overrides) -> dict:
    payload = {
        "customer_id": None,
        "item_description": "Test reel",
        "service_type": "REEL_SERVICE",
        "quoted_cents": 4000,
    }
    payload.update(overrides)
    return payload


def special_order_payload(**overrides) -> dict:
    payload = {
        "customer_id": None,
        "product_id": None,
        "quantity": 1,
    }
    payload.update(overrides)
    return payload


def sale_payload(**overrides) -> dict:
    payload = {"customer_id": None}
    payload.update(overrides)
    return payload


def sale_line_payload(**overrides) -> dict:
    payload = {
        "product_id": None,
        "qty": 1,
    }
    payload.update(overrides)
    return payload
