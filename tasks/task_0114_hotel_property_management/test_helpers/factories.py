"""Payload factories — one per entity, input fields only."""
import itertools

_email_counter = itertools.count(1)


def unique_email(prefix="guest"):
    return f"{prefix}{next(_email_counter)}@example.com"


def create_hotel_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Hotel",
        "current_business_date": "2026-07-01",
        "overbooking_allowance_pct": 0.0,
    }
    defaults.update(overrides)
    return defaults


def create_room_type_payload(hotel_id, **overrides) -> dict:
    defaults = {
        "hotel_id": hotel_id,
        "code": "KING",
        "tier_rank": 1,
        "physical_inventory": 3,
        "base_rate_cents": 20000,
    }
    defaults.update(overrides)
    return defaults


def create_room_payload(hotel_id, room_type_id, **overrides) -> dict:
    defaults = {
        "hotel_id": hotel_id,
        "room_type_id": room_type_id,
        "room_number": "101",
    }
    defaults.update(overrides)
    return defaults


def create_rate_plan_payload(hotel_id, **overrides) -> dict:
    defaults = {
        "hotel_id": hotel_id,
        "code": "BAR",
        "kind": "BAR",
        "adjustment_mode": "FLAT",
        "adjustment_value": 0,
        "no_show_policy": "NONE",
    }
    defaults.update(overrides)
    return defaults


def create_corporate_account_payload(hotel_id, **overrides) -> dict:
    defaults = {
        "hotel_id": hotel_id,
        "name": "Test Corp",
        "credit_limit_cents": 100000,
    }
    defaults.update(overrides)
    return defaults


def create_guest_payload(hotel_id, **overrides) -> dict:
    defaults = {
        "hotel_id": hotel_id,
        "full_name": "Test Guest",
        "email": unique_email(),
    }
    defaults.update(overrides)
    return defaults


def create_group_block_payload(hotel_id, room_type_id, rate_plan_id, **overrides) -> dict:
    defaults = {
        "hotel_id": hotel_id,
        "room_type_id": room_type_id,
        "rate_plan_id": rate_plan_id,
        "block_name": "Test Block",
        "arrival_date": "2026-07-08",
        "departure_date": "2026-07-10",
        "cutoff_date": "2026-07-07",
        "blocked_rooms": 4,
    }
    defaults.update(overrides)
    return defaults


def create_reservation_payload(hotel_id, guest_id, room_type_id, rate_plan_id, **overrides) -> dict:
    defaults = {
        "hotel_id": hotel_id,
        "guest_id": guest_id,
        "room_type_id": room_type_id,
        "rate_plan_id": rate_plan_id,
        "arrival_date": "2026-07-01",
        "departure_date": "2026-07-02",
    }
    defaults.update(overrides)
    return defaults


def create_incidental_payload(hotel_id, folio_id, **overrides) -> dict:
    defaults = {
        "hotel_id": hotel_id,
        "folio_id": folio_id,
        "kind": "CHARGE",
        "description": "Minibar",
        "amount_cents": 1000,
    }
    defaults.update(overrides)
    return defaults


def create_night_audit_run_payload(hotel_id, expected_hotel_version, **overrides) -> dict:
    defaults = {
        "hotel_id": hotel_id,
        "expected_hotel_version": expected_hotel_version,
    }
    defaults.update(overrides)
    return defaults
