"""Payload factories — one per entity, input fields only.

Each factory provides PRD-sensible defaults and accepts **overrides so tests
can pin the exact values a claim needs. Only source: input fields appear here;
computed/system fields (turn_window_end, deposit_required, amount_cents,
no_show_strikes, status, joined_at, to_phone, …) are never sent.

Phone numbers must be unique across customers (E.164); callers that create
several customers must pass distinct `phone` overrides.
"""
import itertools

# Monotonic counter so default phones never collide within a single test.
_phone_counter = itertools.count(1)


def unique_phone() -> str:
    """Return a fresh valid E.164 phone (^\\+[1-9][0-9]{6,14}$)."""
    n = next(_phone_counter)
    return f"+1999{n:07d}"


def create_restaurant_payload(**overrides) -> dict:
    """POST /restaurants input fields. `name` required; everything else has a
    PRD default applied server-side, but the shared fixture convention pins
    timezone "UTC" so local time == UTC."""
    defaults = {
        "name": "Test Restaurant",
        "timezone": "UTC",
    }
    defaults.update(overrides)
    return defaults


def create_dining_area_payload(restaurant_id: str, **overrides) -> dict:
    defaults = {
        "restaurant_id": restaurant_id,
        "name": "MAIN",
        "kind": "STANDARD",
    }
    defaults.update(overrides)
    return defaults


def create_table_payload(dining_area_id: str, **overrides) -> dict:
    """`max_party_size` is required (no default in the PRD)."""
    defaults = {
        "dining_area_id": dining_area_id,
        "label": "T1",
        "min_party_size": 1,
        "max_party_size": 8,
    }
    defaults.update(overrides)
    return defaults


def create_service_period_payload(restaurant_id: str, **overrides) -> dict:
    """`pacing_max_covers_per_slot` is required (no default in the PRD)."""
    defaults = {
        "restaurant_id": restaurant_id,
        "name": "DINNER",
        "start_local_time": "17:00",
        "end_local_time": "23:00",
        "slot_interval_minutes": 30,
        "pacing_max_covers_per_slot": 10,
    }
    defaults.update(overrides)
    return defaults


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Guest",
        "phone": unique_phone(),
    }
    defaults.update(overrides)
    return defaults


def create_reservation_payload(
    restaurant_id: str, customer_id: str, table_id: str,
    expected_table_version: int, **overrides
) -> dict:
    defaults = {
        "restaurant_id": restaurant_id,
        "customer_id": customer_id,
        "table_id": table_id,
        "expected_table_version": expected_table_version,
        "party_size": 2,
        "reservation_start": "2026-06-15T18:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_deposit_hold_payload(**overrides) -> dict:
    defaults = {"card_last4": "4242"}
    defaults.update(overrides)
    return defaults


def create_reschedule_payload(
    table_id: str, expected_table_version: int, reservation_start: str, **overrides
) -> dict:
    defaults = {
        "table_id": table_id,
        "expected_table_version": expected_table_version,
        "reservation_start": reservation_start,
    }
    defaults.update(overrides)
    return defaults


def create_waitlist_entry_payload(
    restaurant_id: str, customer_id: str, **overrides
) -> dict:
    defaults = {
        "restaurant_id": restaurant_id,
        "customer_id": customer_id,
        "party_size": 2,
        "requested_start": "2026-06-15T18:30:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_convert_payload(table_id: str, **overrides) -> dict:
    defaults = {"table_id": table_id}
    defaults.update(overrides)
    return defaults


def create_special_request_payload(**overrides) -> dict:
    defaults = {
        "category": "DIETARY",
        "note": "Test special request note",
    }
    defaults.update(overrides)
    return defaults


def create_private_dining_event_payload(
    restaurant_id: str, dining_area_id: str, customer_id: str, **overrides
) -> dict:
    defaults = {
        "restaurant_id": restaurant_id,
        "dining_area_id": dining_area_id,
        "customer_id": customer_id,
        "party_size": 12,
        "event_start": "2026-06-20T18:00:00Z",
        "event_end": "2026-06-20T22:00:00Z",
        "food_minimum_cents": 200000,
        "deposit_pct": 0.25,
    }
    defaults.update(overrides)
    return defaults


def create_confirm_buyout_payload(expected_dining_area_version: int, **overrides) -> dict:
    defaults = {"expected_dining_area_version": expected_dining_area_version}
    defaults.update(overrides)
    return defaults
