"""Payload factories — one per entity, input fields only."""

# Sensible defaults matching common test scenarios. Every calculation-sensitive
# value can be overridden by the caller.
DEFAULTS = {
    "FLAVOR_STANDARD_COST": 1.80,
    "FLAVOR_PAR": 500,
    "BATCH_UNIT_COST": 1.80,
    "PRODUCED_AT": "2026-05-01T00:00:00Z",
    "EXPIRY_AT": "2026-05-20T00:00:00Z",
    "OPENING_FLOAT": 10000,
}


def create_flavor_payload(**overrides) -> dict:
    defaults = {
        "name": "Vanilla",
        "standard_cost_cents_per_ml": DEFAULTS["FLAVOR_STANDARD_COST"],
        "par_level_ml": DEFAULTS["FLAVOR_PAR"],
    }
    defaults.update(overrides)
    return defaults


def create_size_option_payload(**overrides) -> dict:
    defaults = {
        "code": "SINGLE",
        "scoop_count": 1,
        "base_price_cents": 350,
    }
    defaults.update(overrides)
    return defaults


def create_topping_payload(**overrides) -> dict:
    defaults = {
        "name": "Hot Fudge",
        "price_cents": 100,
    }
    defaults.update(overrides)
    return defaults


def create_event_cart_payload(**overrides) -> dict:
    defaults = {
        "name": "Cart 1",
        "capacity_ml": 5000,
    }
    defaults.update(overrides)
    return defaults


def create_decorating_station_payload(**overrides) -> dict:
    defaults = {
        "name": "Station 1",
    }
    defaults.update(overrides)
    return defaults


def create_batch_payload(flavor_id: str, **overrides) -> dict:
    defaults = {
        "flavor_id": flavor_id,
        "initial_volume_ml": 500,
        "unit_cost_cents_per_ml": DEFAULTS["BATCH_UNIT_COST"],
        "produced_at": DEFAULTS["PRODUCED_AT"],
        "expiry_at": DEFAULTS["EXPIRY_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_waste_event_payload(batch_id: str, waste_type: str, volume_ml: int, **overrides) -> dict:
    defaults = {
        "batch_id": batch_id,
        "waste_type": waste_type,
        "volume_ml": volume_ml,
    }
    defaults.update(overrides)
    return defaults


def create_loyalty_account_payload(**overrides) -> dict:
    defaults = {
        "phone": "555-0100",
    }
    defaults.update(overrides)
    return defaults


def create_drawer_payload(**overrides) -> dict:
    defaults = {
        "opening_float_cents": DEFAULTS["OPENING_FLOAT"],
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(drawer_id: str, **overrides) -> dict:
    defaults = {
        "drawer_id": drawer_id,
    }
    defaults.update(overrides)
    return defaults


def create_order_line_payload(size_option_id: str, flavor_id: str, **overrides) -> dict:
    defaults = {
        "size_option_id": size_option_id,
        "flavor_id": flavor_id,
    }
    defaults.update(overrides)
    return defaults


def create_pre_order_payload(flavor_id: str, decorating_station_id: str, **overrides) -> dict:
    defaults = {
        "flavor_id": flavor_id,
        "decorating_station_id": decorating_station_id,
        "customer_name": "Rey",
        "decorate_start_utc": "2026-05-03T10:00:00Z",
        "decorate_end_utc": "2026-05-03T12:00:00Z",
        "pickup_utc": "2026-05-04T09:00:00Z",
        "quoted_price_cents": 4000,
    }
    defaults.update(overrides)
    return defaults


def create_catering_booking_payload(event_cart_id: str, requested_items, **overrides) -> dict:
    defaults = {
        "event_cart_id": event_cart_id,
        "event_start_utc": "2026-05-02T10:00:00Z",
        "event_end_utc": "2026-05-02T12:00:00Z",
        "requested_items": requested_items,
    }
    defaults.update(overrides)
    return defaults
