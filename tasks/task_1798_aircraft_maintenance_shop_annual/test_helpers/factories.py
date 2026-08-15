"""Payload factories — one per entity, input fields only."""
import itertools

from .constants import TEST_DEFAULTS

_counter = itertools.count(1)


def _seq() -> int:
    return next(_counter)


def create_owner_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "full_name": f"Test Owner {n}",
        "email": f"owner{n}@example.com",
        "phone": f"555-{n:04d}",
        "approval_cap_cents": TEST_DEFAULTS["APPROVAL_CAP_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_aircraft_payload(owner_id: str, **overrides) -> dict:
    n = _seq()
    defaults = {
        "owner_id": owner_id,
        "tail_number": f"N{n:05d}T",
        "make_model": "Cessna 172S",
        "total_time_hours": 100.0,
    }
    defaults.update(overrides)
    return defaults


def create_mechanic_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "full_name": f"Test Mechanic {n}",
        "certificate_number": f"CERT-{n:05d}",
        "certificate_class": "IA",
        "hourly_rate_cents": TEST_DEFAULTS["HOURLY_RATE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_hangar_slot_payload(aircraft_id: str, **overrides) -> dict:
    n = _seq()
    defaults = {
        "hangar_code": f"H{n}",
        "aircraft_id": aircraft_id,
        "starts_at": "2026-08-10T08:00:00Z",
        "ends_at": "2026-08-10T17:00:00Z",
        "daily_rate_cents": TEST_DEFAULTS["DAILY_RATE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_work_order_payload(
    aircraft_id: str,
    hangar_slot_id: str,
    opened_by_mechanic_id: str,
    expected_hangar_slot_version: int,
    **overrides,
) -> dict:
    defaults = {
        "aircraft_id": aircraft_id,
        "hangar_slot_id": hangar_slot_id,
        "opened_by_mechanic_id": opened_by_mechanic_id,
        "scope_type": "ANNUAL",
        "pricing_mode": "HOURLY",
        "expected_hangar_slot_version": expected_hangar_slot_version,
    }
    defaults.update(overrides)
    return defaults


def create_checklist_item_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "item_code": f"C-{n}",
        "description": f"Inspection task {n}",
        "flat_rate_cents": TEST_DEFAULTS["FLAT_RATE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_labor_entry_payload(mechanic_id: str, **overrides) -> dict:
    defaults = {
        "mechanic_id": mechanic_id,
        "duration_tenths": 3,
        "notes": "work performed",
    }
    defaults.update(overrides)
    return defaults


def create_part_payload(discrepancy_id: str, **overrides) -> dict:
    n = _seq()
    defaults = {
        "discrepancy_id": discrepancy_id,
        "part_number": f"PN-{n}",
        "condition": "NEW",
        "unit_cost_cents": 5000,
        "quantity": 1,
    }
    defaults.update(overrides)
    return defaults


def create_directive_payload(aircraft_id: str, **overrides) -> dict:
    n = _seq()
    defaults = {
        "aircraft_id": aircraft_id,
        "directive_type": "AD",
        "reference_number": f"AD-2026-{n:02d}",
        "description": f"Directive {n}",
    }
    defaults.update(overrides)
    return defaults


def create_logbook_entry_payload(
    aircraft_id: str, work_order_id: str, signed_by_mechanic_id: str, **overrides
) -> dict:
    defaults = {
        "aircraft_id": aircraft_id,
        "work_order_id": work_order_id,
        "entry_type": "RTS_STATEMENT",
        "narrative": "Returned to service per 14 CFR 43.11",
        "signed_by_mechanic_id": signed_by_mechanic_id,
    }
    defaults.update(overrides)
    return defaults
