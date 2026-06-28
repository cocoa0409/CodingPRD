"""Payload factories — one per entity, input fields only."""
import itertools

_email_counter = itertools.count(1)
_vin_counter = itertools.count(1)


def unique_email(prefix: str = "rider") -> str:
    return f"{prefix}-{next(_email_counter)}@example.com"


def unique_vin(prefix: str = "VIN") -> str:
    return f"{prefix}-{next(_vin_counter)}"


def member_payload(**overrides) -> dict:
    """Required: full_name, email, date_of_birth. Optional: membership_tier, membership_expires_at."""
    defaults = {
        "full_name": "Test Rider",
        "email": unique_email(),
        "date_of_birth": "1990-01-01",
    }
    defaults.update(overrides)
    return defaults


def guide_payload(**overrides) -> dict:
    """Required: full_name, max_class."""
    defaults = {
        "full_name": "Test Guide",
        "max_class": "TRAIL",
    }
    defaults.update(overrides)
    return defaults


def trail_payload(**overrides) -> dict:
    """Required: name, required_class, max_riders."""
    defaults = {
        "name": "Test Trail",
        "required_class": "TRAIL",
        "max_riders": 10,
    }
    defaults.update(overrides)
    return defaults


def unit_payload(**overrides) -> dict:
    """Required: vin_tag, unit_class, daily_rate_cents, deposit_cents, tank_capacity_liters."""
    defaults = {
        "vin_tag": unique_vin(),
        "unit_class": "TRAIL",
        "daily_rate_cents": 5000,
        "deposit_cents": 25000,
        "tank_capacity_liters": 30,
    }
    defaults.update(overrides)
    return defaults


def gear_payload(**overrides) -> dict:
    """Required: kind, size_code, replacement_cost_cents."""
    defaults = {
        "kind": "HELMET",
        "size_code": "M",
        "replacement_cost_cents": 12000,
    }
    defaults.update(overrides)
    return defaults


def departure_payload(trail_id, **overrides) -> dict:
    """Required: trail_id, starts_at, ends_at, required_guide_class, capacity_riders."""
    defaults = {
        "trail_id": trail_id,
        "starts_at": "2026-12-01T09:00:00Z",
        "ends_at": "2026-12-01T12:00:00Z",
        "required_guide_class": "TRAIL",
        "capacity_riders": 10,
    }
    defaults.update(overrides)
    return defaults


def reservation_payload(member_id, tour_departure_id, unit_id, **overrides) -> dict:
    """Required: member_id, tour_departure_id, unit_id. Optional: helmet_gear_id, suit_gear_id."""
    defaults = {
        "member_id": member_id,
        "tour_departure_id": tour_departure_id,
        "unit_id": unit_id,
    }
    defaults.update(overrides)
    return defaults
