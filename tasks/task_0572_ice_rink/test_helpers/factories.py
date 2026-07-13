"""Payload factories — one per entity, input fields only."""


def create_rink_payload(**overrides) -> dict:
    defaults = {
        "name": "Main",
        "resurface_buffer_minutes": 15,
        "public_skate_capacity": 2,
        "public_skate_fee_cents": 0,
        "rental_skate_count": 1,
        "locker_count": 3,
        "locker_fee_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_skater_payload(**overrides) -> dict:
    defaults = {"full_name": "Skater", "email": "skater@x.com"}
    defaults.update(overrides)
    return defaults


def create_ice_slot_payload(**overrides) -> dict:
    defaults = {
        "purpose": "PUBLIC_SKATE",
        "start_utc": "2026-06-10T08:00:00Z",
        "end_utc": "2026-06-10T09:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_admission_payload(**overrides) -> dict:
    defaults = {}
    defaults.update(overrides)
    return defaults


def create_class_payload(**overrides) -> dict:
    defaults = {"level_name": "BASIC_1", "capacity": 5}
    defaults.update(overrides)
    return defaults


def create_enrollment_payload(**overrides) -> dict:
    defaults = {}
    defaults.update(overrides)
    return defaults


def create_tuition_subscription_payload(**overrides) -> dict:
    defaults = {
        "monthly_fee_cents": 12000,
        "billing_cycle_start": "2026-06-01",
        "billing_cycle_end": "2026-07-01",
        "total_sessions_in_cycle": 8,
    }
    defaults.update(overrides)
    return defaults


def create_league_payload(**overrides) -> dict:
    defaults = {
        "name": "Beer League",
        "sport": "HOCKEY",
        "season_start": "2026-06-01",
        "season_end": "2026-09-01",
        "roster_capacity": 20,
    }
    defaults.update(overrides)
    return defaults


def create_registration_payload(**overrides) -> dict:
    defaults = {}
    defaults.update(overrides)
    return defaults


def create_locker_assignment_payload(**overrides) -> dict:
    defaults = {
        "locker_number": 1,
        "season_start_date": "2026-06-01",
        "season_end_date": "2026-09-01",
    }
    defaults.update(overrides)
    return defaults


def create_slot_booking_payload(**overrides) -> dict:
    defaults = {"booking_type": "PRIVATE_RENTAL"}
    defaults.update(overrides)
    return defaults


def create_sharpening_order_payload(**overrides) -> dict:
    defaults = {"skate_type": "HOCKEY", "price_cents": 900}
    defaults.update(overrides)
    return defaults
