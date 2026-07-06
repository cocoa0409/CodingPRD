"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "VENUE_NAME": "Test Drive-In",
    "FM_POOL": ["87.9", "88.1", "88.3"],
    "LOT_NAME": "Test Lot",
    "STALL_COUNT": 10,
    "PERSON_CAPACITY": 100,
    "FILM_TITLE": "Test Film",
    "RUNTIME_MINUTES": 100,
    "RATING": "G",
    "BASE_PRICE_CENTS": 2000,
    "ITEM_NAME": "Test Item",
    "UNIT_PRICE_CENTS": 350,
}


def create_venue_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["VENUE_NAME"],
        "fm_channel_pool": list(DEFAULTS["FM_POOL"]),
    }
    defaults.update(overrides)
    return defaults


def create_lot_payload(venue_id, **overrides) -> dict:
    defaults = {
        "venue_id": venue_id,
        "name": DEFAULTS["LOT_NAME"],
        "stall_count": DEFAULTS["STALL_COUNT"],
        "person_capacity": DEFAULTS["PERSON_CAPACITY"],
    }
    defaults.update(overrides)
    return defaults


def create_film_payload(**overrides) -> dict:
    defaults = {
        "title": DEFAULTS["FILM_TITLE"],
        "runtime_minutes": DEFAULTS["RUNTIME_MINUTES"],
        "rating": DEFAULTS["RATING"],
    }
    defaults.update(overrides)
    return defaults


def create_concession_item_payload(venue_id, **overrides) -> dict:
    defaults = {
        "venue_id": venue_id,
        "name": DEFAULTS["ITEM_NAME"],
        "unit_price_cents": DEFAULTS["UNIT_PRICE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_showtime_payload(venue_id, lot_id, primary_film_id, start_utc, **overrides) -> dict:
    defaults = {
        "venue_id": venue_id,
        "lot_id": lot_id,
        "primary_film_id": primary_film_id,
        "is_double_feature": False,
        "start_utc": start_utc,
        "pricing_mode": "PER_CAR",
        "base_price_cents": DEFAULTS["BASE_PRICE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_reservation_payload(showtime_id, patron_id, expected_showtime_version, **overrides) -> dict:
    defaults = {
        "showtime_id": showtime_id,
        "patron_id": patron_id,
        "occupant_count": 2,
        "expected_showtime_version": expected_showtime_version,
    }
    defaults.update(overrides)
    return defaults


def create_concession_order_payload(lines, **overrides) -> dict:
    defaults = {"lines": lines}
    defaults.update(overrides)
    return defaults


def create_season_pass_payload(patron_id, valid_from_utc, valid_to_utc, **overrides) -> dict:
    defaults = {
        "patron_id": patron_id,
        "tier": "GOLD",
        "max_redemptions": 3,
        "valid_from_utc": valid_from_utc,
        "valid_to_utc": valid_to_utc,
    }
    defaults.update(overrides)
    return defaults


def create_private_rental_payload(venue_id, lot_id, organizer_id, start_utc, end_utc, **overrides) -> dict:
    defaults = {
        "venue_id": venue_id,
        "lot_id": lot_id,
        "organizer_id": organizer_id,
        "start_utc": start_utc,
        "end_utc": end_utc,
        "flat_venue_fee_cents": 100000,
        "per_hour_cents": 10000,
    }
    defaults.update(overrides)
    return defaults


def create_weather_event_payload(severity, **overrides) -> dict:
    defaults = {"severity": severity}
    defaults.update(overrides)
    return defaults
