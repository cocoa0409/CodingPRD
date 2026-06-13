"""Payload factories — one per entity, input fields only.

Field names are PRD-exact. Optional fields with PRD-declared defaults are
omitted from the base payloads unless a caller overrides them.
"""
import itertools

_email_counter = itertools.count(1)
_code_counter = itertools.count(1)


def unique_email(prefix: str = "cust") -> str:
    """Generate a unique customer email so duplicate-email tests stay isolated."""
    return f"{prefix}{next(_email_counter)}@example.com"


def unique_code(prefix: str = "GC") -> str:
    """Generate a unique gift-card code within a venue."""
    return f"{prefix}-{next(_code_counter)}"


def create_venue_payload(**overrides) -> dict:
    """Venue input fields (PRD Section 3.1).

    no_show_fee_pct / no_show_strike_limit are optional (defaults 0.5 / 3) —
    omitted unless overridden.
    """
    defaults = {
        "name": "Test Venue",
        "timezone": "UTC",
        "open_minute_of_day": 0,
        "close_minute_of_day": 1440,
    }
    defaults.update(overrides)
    return defaults


def create_room_payload(venue_id: str, **overrides) -> dict:
    """Room input fields (PRD Section 3.1).

    min_age / waiver_required / private_surcharge_cents / reset_buffer_minutes
    are optional — omitted unless overridden.
    """
    defaults = {
        "venue_id": venue_id,
        "name": "Test Room",
        "min_group_size": 1,
        "max_group_size": 8,
        "base_price_cents": 2000,
        "game_minutes": 60,
    }
    defaults.update(overrides)
    return defaults


def create_pricing_rule_payload(venue_id: str, room_id: str, **overrides) -> dict:
    """PricingRule input fields (PRD Section 3.1).

    peak_multiplier_bps / large_group_multiplier_bps are optional (default 10000).
    """
    defaults = {
        "venue_id": venue_id,
        "room_id": room_id,
        "peak_dow_mask": 0,
        "peak_start_minute_of_day": 720,
        "peak_end_minute_of_day": 1080,
        "large_group_threshold": 99,
    }
    defaults.update(overrides)
    return defaults


def create_game_master_payload(venue_id: str, **overrides) -> dict:
    """GameMaster input fields (PRD Section 3.2)."""
    defaults = {
        "venue_id": venue_id,
        "full_name": "Test GM",
    }
    defaults.update(overrides)
    return defaults


def create_time_slot_payload(room_id: str, start_utc: str, **overrides) -> dict:
    """TimeSlot input fields (PRD Section 3.2)."""
    defaults = {
        "room_id": room_id,
        "start_utc": start_utc,
    }
    defaults.update(overrides)
    return defaults


def create_customer_payload(**overrides) -> dict:
    """Customer input fields (PRD Section 3.3)."""
    defaults = {
        "email": unique_email(),
        "full_name": "Test Customer",
    }
    defaults.update(overrides)
    return defaults


def create_booking_payload(time_slot_id: str, customer_id: str, group_size: int,
                           expected_time_slot_version: int, **overrides) -> dict:
    """Booking-create input fields (PRD Section 3.3).

    is_private is optional (default false).
    """
    defaults = {
        "time_slot_id": time_slot_id,
        "customer_id": customer_id,
        "group_size": group_size,
        "expected_time_slot_version": expected_time_slot_version,
    }
    defaults.update(overrides)
    return defaults


def create_participant_payload(display_name: str = "Test Participant", age: int = 30,
                               **overrides) -> dict:
    """Participant input fields (PRD Section 3.4)."""
    defaults = {
        "display_name": display_name,
        "age": age,
    }
    defaults.update(overrides)
    return defaults


def create_gift_card_payload(venue_id: str, initial_balance_cents: int = 5000,
                             **overrides) -> dict:
    """GiftCard input fields (PRD Section 3.9)."""
    defaults = {
        "venue_id": venue_id,
        "code": unique_code(),
        "initial_balance_cents": initial_balance_cents,
    }
    defaults.update(overrides)
    return defaults
