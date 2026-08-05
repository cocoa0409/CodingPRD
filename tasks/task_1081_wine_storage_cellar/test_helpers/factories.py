"""Payload factories — one per entity, input fields only (Wine-Storage Cellar PRD)."""
import itertools

_counter = itertools.count(1)


def _uniq() -> int:
    return next(_counter)


def create_member_payload(**overrides) -> dict:
    n = _uniq()
    defaults = {
        "full_name": f"Member {n}",
        "email": f"member{n}@example.com",
        "membership_tier": "STANDARD",
    }
    defaults.update(overrides)
    return defaults


def create_locker_payload(**overrides) -> dict:
    n = _uniq()
    defaults = {
        "label": f"L-{n}",
        "size_tier": "MEDIUM",
        "climate_zone": "RED",
        "capacity_bottles": 3,
    }
    defaults.update(overrides)
    return defaults


def create_bottle_payload(**overrides) -> dict:
    defaults = {
        "locker_id": None,
        "wine_name": "Test Cuvee",
        "vintage_year": 2015,
        "varietal": "Cabernet",
        "format_ml": 750,
        "drink_window_start_year": 2018,
        "drink_window_end_year": 2040,
    }
    defaults.update(overrides)
    return defaults


def create_appraisal_payload(**overrides) -> dict:
    defaults = {
        "bottle_id": None,
        "method": "MARKET_COMPARABLE",
        "base_value_cents": 1_000_000,
    }
    defaults.update(overrides)
    return defaults


def create_insurance_policy_payload(**overrides) -> dict:
    defaults = {
        "member_id": None,
        "coverage_tier": "FULL",
        "covered_bottle_ids": [],
    }
    defaults.update(overrides)
    return defaults


def create_movement_request_payload(**overrides) -> dict:
    defaults = {
        "member_id": None,
        "locker_id": None,
        "request_type": "INTAKE",
        "quantity": 1,
    }
    defaults.update(overrides)
    return defaults


def create_delivery_order_payload(**overrides) -> dict:
    defaults = {
        "member_id": None,
        "bottle_ids": [],
        "courier_ref": "CX-1",
        "slot_start": "2026-06-01T10:00:00Z",
        "slot_end": "2026-06-01T12:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_consignment_payload(**overrides) -> dict:
    defaults = {
        "bottle_id": None,
        "reserve_price_cents": 1_000_000,
    }
    defaults.update(overrides)
    return defaults


def create_waitlist_entry_payload(**overrides) -> dict:
    defaults = {
        "member_id": None,
        "requested_size_tier": "MEDIUM",
        "requested_climate_zone": "RED",
    }
    defaults.update(overrides)
    return defaults


def create_maintenance_window_payload(**overrides) -> dict:
    defaults = {
        "locker_id": None,
        "window_start": "2026-06-01T10:00:00Z",
        "window_end": "2026-06-01T12:00:00Z",
        "reason": "routine service",
    }
    defaults.update(overrides)
    return defaults


def create_ledger_adjustment_payload(**overrides) -> dict:
    defaults = {
        "entry_type": "DEBIT",
        "amount_cents": 1000,
        "reason": "adjustment",
    }
    defaults.update(overrides)
    return defaults


def create_climate_reading_payload(**overrides) -> dict:
    defaults = {
        "locker_id": None,
        "temperature_c": 13.0,
        "humidity_pct": 70.0,
    }
    defaults.update(overrides)
    return defaults
