"""Payload factories — one per entity, input fields only.

Field names are exact PRD names. Only source: input fields appear here;
system/computed fields are never sent by the client.
"""
from .constants import TEST_DEFAULTS


def create_gear_type_payload(**overrides) -> dict:
    """GearType create payload. requires_lesson_for_beginner and active are optional."""
    defaults = {
        "category": "KAYAK",
        "name": "Test Gear Type",
        "size_label": "M",
    }
    defaults.update(overrides)
    return defaults


def create_rate_card_payload(gear_type_id, **overrides) -> dict:
    """RateCard create payload. grace_minutes and active are optional."""
    defaults = {
        "gear_type_id": gear_type_id,
        "hourly_cents": TEST_DEFAULTS["HOURLY_CENTS"],
        "daily_cents": TEST_DEFAULTS["DAILY_CENTS"],
        "seasonal_flat_cents": TEST_DEFAULTS["SEASONAL_FLAT_CENTS"],
        "deposit_cents": TEST_DEFAULTS["DEPOSIT_CENTS"],
        "damage_waiver_cents_per_day": TEST_DEFAULTS["DAMAGE_WAIVER_CENTS_PER_DAY"],
        "late_fee_cents_per_hour": TEST_DEFAULTS["LATE_FEE_CENTS_PER_HOUR"],
        "loss_fee_cents": TEST_DEFAULTS["LOSS_FEE_CENTS"],
        "grace_minutes": TEST_DEFAULTS["GRACE_MINUTES"],
    }
    defaults.update(overrides)
    return defaults


def create_season_window_payload(**overrides) -> dict:
    """SeasonWindow create payload."""
    defaults = {
        "category": "SKI",
        "label": "Peak",
        "starts_on": "2026-01-15T00:00:00Z",
        "ends_on": "2026-03-01T00:00:00Z",
        "demand_multiplier_bp": 12000,
    }
    defaults.update(overrides)
    return defaults


def create_addon_payload(**overrides) -> dict:
    """AddOn create payload. capacity_per_slot and active are optional."""
    defaults = {
        "kind": "PACKAGE",
        "category": "SUP",
        "name": "Test Add-On",
        "price_cents": 500,
    }
    defaults.update(overrides)
    return defaults


def create_customer_payload(**overrides) -> dict:
    """Customer create payload. skill_level is optional (defaults BEGINNER)."""
    defaults = {
        "full_name": "Test Renter",
        "email": "renter@example.com",
    }
    defaults.update(overrides)
    return defaults


def create_gear_unit_payload(gear_type_id, rate_card_id, **overrides) -> dict:
    """GearUnit create payload."""
    defaults = {
        "gear_type_id": gear_type_id,
        "rate_card_id": rate_card_id,
        "asset_tag": "ASSET-1",
    }
    defaults.update(overrides)
    return defaults


def create_reservation_payload(customer_id, gear_unit_id, expected_gear_unit_version,
                               pickup_at, due_at, **overrides) -> dict:
    """Reservation create payload. damage_waiver_opted optional (defaults false)."""
    defaults = {
        "customer_id": customer_id,
        "gear_unit_id": gear_unit_id,
        "pickup_at": pickup_at,
        "due_at": due_at,
        "expected_gear_unit_version": expected_gear_unit_version,
    }
    defaults.update(overrides)
    return defaults


def attach_addon_payload(addon_id, **overrides) -> dict:
    """ReservationAddOn attach payload. slot_start_at/slot_end_at optional (LESSON only)."""
    defaults = {"addon_id": addon_id}
    defaults.update(overrides)
    return defaults


def checkout_payload(condition_rating="GOOD", **overrides) -> dict:
    """Checkout payload: condition_rating required, notes optional."""
    defaults = {"condition_rating": condition_rating}
    defaults.update(overrides)
    return defaults


def checkin_payload(condition_rating="GOOD", **overrides) -> dict:
    """Checkin payload: condition_rating required, notes optional."""
    defaults = {"condition_rating": condition_rating}
    defaults.update(overrides)
    return defaults
