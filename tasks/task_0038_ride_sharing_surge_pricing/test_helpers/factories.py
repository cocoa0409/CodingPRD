"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "ZONE_NAME": "Test Zone",
    "BASE_FARE_CENTS": 1000,
    "RIDER_NAME": "Test Rider",
    "DRIVER_NAME": "Test Driver",
    "EFFECTIVE_FROM": "2026-06-01T00:00:00Z",
    "EFFECTIVE_TO": "2026-06-01T01:00:00Z",
    "WINDOW_START": "2026-06-01T10:00:00Z",
    "WINDOW_END": "2026-06-01T12:00:00Z",
}


def create_zone_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["ZONE_NAME"],
        "grid_code": "A1",
        "base_fare_cents": DEFAULTS["BASE_FARE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_rider_payload(home_zone_id, **overrides) -> dict:
    defaults = {
        "name": DEFAULTS["RIDER_NAME"],
        "home_zone_id": home_zone_id,
    }
    defaults.update(overrides)
    return defaults


def create_driver_payload(home_zone_id, **overrides) -> dict:
    defaults = {
        "name": DEFAULTS["DRIVER_NAME"],
        "home_zone_id": home_zone_id,
    }
    defaults.update(overrides)
    return defaults


def create_surge_snapshot_payload(observed_demand, observed_supply, expected_zone_version,
                                  **overrides) -> dict:
    defaults = {
        "observed_demand": observed_demand,
        "observed_supply": observed_supply,
        "is_rush_hour": False,
        "effective_from": DEFAULTS["EFFECTIVE_FROM"],
        "effective_to": DEFAULTS["EFFECTIVE_TO"],
        "expected_zone_version": expected_zone_version,
    }
    defaults.update(overrides)
    return defaults


def create_trip_payload(rider_id, pickup_zone_id, dropoff_zone_id, **overrides) -> dict:
    defaults = {
        "rider_id": rider_id,
        "pickup_zone_id": pickup_zone_id,
        "dropoff_zone_id": dropoff_zone_id,
    }
    defaults.update(overrides)
    return defaults


def create_airport_queue_payload(zone_id, driver_id, **overrides) -> dict:
    defaults = {
        "zone_id": zone_id,
        "driver_id": driver_id,
    }
    defaults.update(overrides)
    return defaults


def create_quest_payload(driver_id, **overrides) -> dict:
    defaults = {
        "driver_id": driver_id,
        "target_trips": 3,
        "bonus_cents": 5000,
        "window_start": DEFAULTS["WINDOW_START"],
        "window_end": DEFAULTS["WINDOW_END"],
    }
    defaults.update(overrides)
    return defaults


def create_dispute_payload(trip_id, **overrides) -> dict:
    defaults = {
        "trip_id": trip_id,
        "reason": "OVERCHARGED",
        "requested_refund_cents": 500,
    }
    defaults.update(overrides)
    return defaults
