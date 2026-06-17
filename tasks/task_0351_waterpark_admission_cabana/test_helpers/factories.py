"""Payload factories — one per entity, input fields only (PRD §3)."""

DEFAULTS = {
    "PARK_NAME": "Test Waterpark",
    "TOTAL_GATE_CAPACITY": 1000,
    "BASE_PRICE_CENTS": 5000,
    "WINDOW_CAPACITY": 50,
    "GUEST_NAME": "Test Guest",
    "GUEST_EMAIL": "guest@example.com",
    "GUEST_ZIP": "00000",
    "GUEST_HEIGHT_CM": 150,
    "CABANA_LABEL": "C-1",
    "CABANA_RATE_CENTS": 9000,
    "LOCKER_BANK": "A",
    "LOCKER_RATE_CENTS": 500,
}


def create_park_payload(**overrides) -> dict:
    """Park input fields: name, timezone?, total_gate_capacity,
    resident_zip_prefixes?, rain_check_value_cents? (PRD §3.1)."""
    defaults = {
        "name": DEFAULTS["PARK_NAME"],
        "total_gate_capacity": DEFAULTS["TOTAL_GATE_CAPACITY"],
    }
    defaults.update(overrides)
    return defaults


def create_pricing_policy_payload(park_id, **overrides) -> dict:
    """PricingPolicy input fields: park_id, product_type, base_price_cents,
    resident_discount_pct?, group_threshold?, group_discount_pct?, combo_price_cents? (PRD §3.2)."""
    defaults = {
        "park_id": park_id,
        "product_type": "DAY_TICKET",
        "base_price_cents": DEFAULTS["BASE_PRICE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_entry_window_payload(**overrides) -> dict:
    """EntryWindow input fields: starts_at, ends_at, window_capacity (PRD §3.1)."""
    defaults = {
        "starts_at": "2026-07-01T09:00:00Z",
        "ends_at": "2026-07-01T17:00:00Z",
        "window_capacity": DEFAULTS["WINDOW_CAPACITY"],
    }
    defaults.update(overrides)
    return defaults


def create_cabana_payload(**overrides) -> dict:
    """Cabana input fields: label, tier, daily_rate_cents, turnover_buffer_minutes? (PRD §3.1)."""
    defaults = {
        "label": DEFAULTS["CABANA_LABEL"],
        "tier": "STANDARD",
        "daily_rate_cents": DEFAULTS["CABANA_RATE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_locker_payload(**overrides) -> dict:
    """Locker input fields: bank_code, hourly_rate_cents (PRD §3.1)."""
    defaults = {
        "bank_code": DEFAULTS["LOCKER_BANK"],
        "hourly_rate_cents": DEFAULTS["LOCKER_RATE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_guest_payload(**overrides) -> dict:
    """Guest input fields: full_name, email, zip_code, height_cm (PRD §3.4)."""
    defaults = {
        "full_name": DEFAULTS["GUEST_NAME"],
        "email": DEFAULTS["GUEST_EMAIL"],
        "zip_code": DEFAULTS["GUEST_ZIP"],
        "height_cm": DEFAULTS["GUEST_HEIGHT_CM"],
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(park_id, guest_id, **overrides) -> dict:
    """Order input fields: park_id, guest_id, product_type, party_size,
    food_beverage_combo? (PRD §3.3)."""
    defaults = {
        "park_id": park_id,
        "guest_id": guest_id,
        "product_type": "DAY_TICKET",
        "party_size": 1,
    }
    defaults.update(overrides)
    return defaults


def assign_window_payload(entry_window_id, expected_entry_window_version, **overrides) -> dict:
    """assign-window input fields: entry_window_id, expected_entry_window_version (PRD §3.4, §2.6)."""
    defaults = {
        "entry_window_id": entry_window_id,
        "expected_entry_window_version": expected_entry_window_version,
    }
    defaults.update(overrides)
    return defaults


def bind_guest_payload(guest_id, **overrides) -> dict:
    """bind-guest input field: guest_id (PRD §3.4)."""
    defaults = {"guest_id": guest_id}
    defaults.update(overrides)
    return defaults


def create_cabana_rental_payload(cabana_id, order_id, entry_window_id,
                                 starts_at, ends_at, expected_entry_window_version,
                                 **overrides) -> dict:
    """CabanaRental input fields: cabana_id, order_id, entry_window_id, starts_at,
    ends_at, expected_entry_window_version (PRD §3.6)."""
    defaults = {
        "cabana_id": cabana_id,
        "order_id": order_id,
        "entry_window_id": entry_window_id,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "expected_entry_window_version": expected_entry_window_version,
    }
    defaults.update(overrides)
    return defaults


def create_locker_rental_payload(locker_id, order_id, starts_at, ends_at, **overrides) -> dict:
    """LockerRental input fields: locker_id, order_id, starts_at, ends_at (PRD §3.7)."""
    defaults = {
        "locker_id": locker_id,
        "order_id": order_id,
        "starts_at": starts_at,
        "ends_at": ends_at,
    }
    defaults.update(overrides)
    return defaults


def weather_payload(weather_status, **overrides) -> dict:
    """weather input field: weather_status (PRD §3.1)."""
    defaults = {"weather_status": weather_status}
    defaults.update(overrides)
    return defaults


def clock_payload(to_iso8601, **overrides) -> dict:
    """clock input field: to_iso8601 (PRD §3.9)."""
    defaults = {"to_iso8601": to_iso8601}
    defaults.update(overrides)
    return defaults


def close_window_payload(force=None, **overrides) -> dict:
    """close input field: force? (PRD §3.1)."""
    defaults = {}
    if force is not None:
        defaults["force"] = force
    defaults.update(overrides)
    return defaults
