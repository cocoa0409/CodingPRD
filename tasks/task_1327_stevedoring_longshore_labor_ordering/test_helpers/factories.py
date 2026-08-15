"""Payload factories — one per creatable resource, input fields only.

Registration numbers, voyage numbers, and unit codes are auto-uniquified so
several factories can be called within a single test without colliding on the
uniqueness rules (PRD §3.1/§3.3/§3.4).
"""
import itertools

_COUNTER = itertools.count(1)

DEFAULTS = {
    "VESSEL_NAME": "MV Test",
    "SHIPPING_LINE": "LineCo",
    "ETA_UTC": "2026-08-09T00:00:00Z",
    "PLANNED_MOVES": 10,
    "PLANNED_TONS": 5,
    "MPH_TARGET": 20.0,
    "CREDIT_LIMIT_CENTS": 1_000_000,
    "SHIFT_DATE": "2026-08-10",
    "SHIFT_START": "2026-08-10T08:00:00Z",
    "SHIFT_END": "2026-08-10T16:00:00Z",
    "PERIOD": "DAY",
    "GANG_TYPE": "GENERAL",
    "CLASSIFICATION": "HOLDMAN",
    "REQUIRED_HEADCOUNT": 1,
    "EQUIPMENT_TYPE": "RTG",
    "REQUIRED_EQUIPMENT_COUNT": 0,
    "REGISTERED_ON": "2010-01-01",
    "BASE_RATE_CENTS": 4000,
    "WINDOW_START": "2026-08-10T08:00:00Z",
    "WINDOW_END": "2026-08-10T16:00:00Z",
}


def create_vessel_call_payload(**overrides) -> dict:
    n = next(_COUNTER)
    defaults = {
        "vessel_name": f"{DEFAULTS['VESSEL_NAME']} {n}",
        "voyage_number": f"VOY-{n:05d}",
        "shipping_line": DEFAULTS["SHIPPING_LINE"],
        "eta_utc": DEFAULTS["ETA_UTC"],
        "planned_moves": DEFAULTS["PLANNED_MOVES"],
        "planned_tons": DEFAULTS["PLANNED_TONS"],
        "contracted_mph_target": DEFAULTS["MPH_TARGET"],
        "credit_limit_cents": DEFAULTS["CREDIT_LIMIT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_shift_window_payload(vessel_call_id, **overrides) -> dict:
    defaults = {
        "vessel_call_id": vessel_call_id,
        "shift_date": DEFAULTS["SHIFT_DATE"],
        "period": DEFAULTS["PERIOD"],
        "start_utc": DEFAULTS["SHIFT_START"],
        "end_utc": DEFAULTS["SHIFT_END"],
    }
    defaults.update(overrides)
    return defaults


def create_gang_order_payload(shift_window_id, **overrides) -> dict:
    defaults = {
        "shift_window_id": shift_window_id,
        "gang_type": DEFAULTS["GANG_TYPE"],
        "required_classification": DEFAULTS["CLASSIFICATION"],
        "required_headcount": DEFAULTS["REQUIRED_HEADCOUNT"],
        "required_equipment_type": DEFAULTS["EQUIPMENT_TYPE"],
        "required_equipment_count": DEFAULTS["REQUIRED_EQUIPMENT_COUNT"],
    }
    defaults.update(overrides)
    return defaults


def create_worker_payload(**overrides) -> dict:
    n = next(_COUNTER)
    defaults = {
        "full_name": f"Worker {n}",
        "registration_number": f"REG-{n:05d}",
        "classification": DEFAULTS["CLASSIFICATION"],
        "registered_on": DEFAULTS["REGISTERED_ON"],
        "base_hourly_rate_cents": DEFAULTS["BASE_RATE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_equipment_unit_payload(**overrides) -> dict:
    n = next(_COUNTER)
    defaults = {
        "unit_code": f"UNIT-{n:05d}",
        "equipment_type": DEFAULTS["EQUIPMENT_TYPE"],
    }
    defaults.update(overrides)
    return defaults


def create_equipment_assignment_payload(gang_order_id, equipment_unit_id, **overrides) -> dict:
    defaults = {
        "gang_order_id": gang_order_id,
        "equipment_unit_id": equipment_unit_id,
        "window_start_utc": DEFAULTS["WINDOW_START"],
        "window_end_utc": DEFAULTS["WINDOW_END"],
    }
    defaults.update(overrides)
    return defaults


def create_move_record_payload(gang_order_id, **overrides) -> dict:
    defaults = {
        "gang_order_id": gang_order_id,
        "period_start_utc": "2026-08-10T08:00:00Z",
        "period_end_utc": "2026-08-10T09:00:00Z",
        "moves_count": 10,
        "tons_lifted": 5,
        "stoppage_minutes": 0,
    }
    defaults.update(overrides)
    return defaults


def create_damage_claim_payload(gang_order_id, **overrides) -> dict:
    n = next(_COUNTER)
    defaults = {
        "gang_order_id": gang_order_id,
        "cargo_ref": f"MSKU-{n:06d}",
        "damage_description": "Damage reported during operations",
        "estimated_amount_cents": 100_000,
    }
    defaults.update(overrides)
    return defaults


def create_safety_incident_payload(vessel_call_id, **overrides) -> dict:
    defaults = {
        "vessel_call_id": vessel_call_id,
        "scope": "VESSEL",
        "severity": "CRITICAL",
        "description": "Safety incident reported",
    }
    defaults.update(overrides)
    return defaults


def create_timesheet_entry_payload(gang_order_id, worker_id, **overrides) -> dict:
    defaults = {
        "gang_order_id": gang_order_id,
        "worker_id": worker_id,
        "work_minutes": 480,
        "meal_break_taken": True,
    }
    defaults.update(overrides)
    return defaults


def create_invoice_payload(vessel_call_id, **overrides) -> dict:
    defaults = {"vessel_call_id": vessel_call_id}
    defaults.update(overrides)
    return defaults
