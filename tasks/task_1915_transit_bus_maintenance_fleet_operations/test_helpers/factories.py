"""Payload factories — one per entity, input fields only (PRD §4 payloads).

Labor-entry shift types follow the PRD §3.5 differential table: AM (1.00),
PM (1.10), NIGHT (1.25).
"""
import itertools

from .constants import TEST_DEFAULTS

_counter = itertools.count(1)


def _uniq(prefix: str) -> str:
    return f"{prefix}-{next(_counter):04d}"


def create_bus_payload(**overrides) -> dict:
    n = next(_counter)
    defaults = {
        "fleet_number": f"F{n:04d}",
        "vin": f"VIN{n:014d}",
        "model_year": TEST_DEFAULTS["MODEL_YEAR"],
        "in_service_date": TEST_DEFAULTS["IN_SERVICE_DATE"],
        "initial_odometer_miles": 10_000,
        "replacement_cost_cents": TEST_DEFAULTS["REPLACEMENT_COST_CENTS"],
        "base_warranty_expiry_miles": 150_000,
        "base_warranty_expiry_date": "2028-01-01",
        "overhaul_interval_miles": TEST_DEFAULTS["OVERHAUL_INTERVAL_MILES"],
    }
    defaults.update(overrides)
    return defaults


def create_pm_policy_payload(**overrides) -> dict:
    defaults = {
        "level_a_interval_miles": 6_000,
        "level_b_interval_miles": 18_000,
        "level_c_interval_miles": 36_000,
        "tolerance_miles": 500,
        "calendar_interval_days": 180,
    }
    defaults.update(overrides)
    return defaults


def create_mechanic_payload(**overrides) -> dict:
    defaults = {
        "name": _uniq("Mechanic"),
        "employee_ref": _uniq("EMP"),
    }
    defaults.update(overrides)
    return defaults


def create_certification_payload(**overrides) -> dict:
    defaults = {
        "cert_type": "ENGINE",
        "issued_date": "2026-01-01",
        "expiry_date": "2027-01-01",
    }
    defaults.update(overrides)
    return defaults


def create_shift_payload(**overrides) -> dict:
    defaults = {
        "shift_date": "2026-08-10",
        "shift_type": "AM",
        "required_headcount": {},
    }
    defaults.update(overrides)
    return defaults


def create_shift_assignment_payload(mechanic_id: str, **overrides) -> dict:
    defaults = {
        "mechanic_id": mechanic_id,
        "role_in_shift": "TECH",
    }
    defaults.update(overrides)
    return defaults


def create_part_payload(**overrides) -> dict:
    defaults = {
        "sku": _uniq("SKU"),
        "description": "Test part",
        "part_class": "CONSUMABLE",
        "unit_cost_cents": 1_000,
        "reorder_point": 0,
        "initial_on_hand": 10,
        "warranty_eligible": False,
    }
    defaults.update(overrides)
    return defaults


def create_work_order_payload(bus_id: str, expected_bus_version: int, **overrides) -> dict:
    defaults = {
        "bus_id": bus_id,
        "wo_type": "CORRECTIVE",
        "priority": "ROUTINE",
        "planned_start_date": "2026-08-02",
        "planned_end_date": "2026-08-03",
        "estimated_labor_hours": 1,
        "estimated_cost_cents": 6_500,
        "expected_bus_version": expected_bus_version,
    }
    defaults.update(overrides)
    return defaults


def create_part_line_payload(part_id: str, **overrides) -> dict:
    defaults = {
        "part_id": part_id,
        "qty": 1,
    }
    defaults.update(overrides)
    return defaults


def create_defect_payload(bus_id: str, **overrides) -> dict:
    defaults = {
        "bus_id": bus_id,
        "severity": "MINOR",
        "defect_code": "OTHER",
        "description": "Test defect",
        "odometer_at_report": 10_000,
    }
    defaults.update(overrides)
    return defaults


def create_campaign_payload(**overrides) -> dict:
    defaults = {
        "code": _uniq("CMP"),
        "title": "Test campaign",
        "model_year_from": 2020,
        "model_year_to": 2022,
        "labor_hours_per_bus": 2,
        "deadline_date": "2026-12-31",
    }
    defaults.update(overrides)
    return defaults


def create_mileage_log_payload(bus_id: str, **overrides) -> dict:
    defaults = {
        "bus_id": bus_id,
        "log_date": "2026-08-01",
        "odometer_end": 10_100,
        "fuel_gallons": 50,
    }
    defaults.update(overrides)
    return defaults


def create_inspection_payload(bus_id: str, **overrides) -> dict:
    defaults = {
        "bus_id": bus_id,
        "test_type": "OBD",
        "test_date": "2026-08-01",
        "result": "PASS",
        "certificate_expiry_date": "2027-08-01",
    }
    defaults.update(overrides)
    return defaults


def create_claim_payload(work_order_id: str, expected_work_order_version: int, **overrides) -> dict:
    defaults = {
        "work_order_id": work_order_id,
        "claim_type": "BASE_OEM",
        "expected_work_order_version": expected_work_order_version,
    }
    defaults.update(overrides)
    return defaults


def create_replacement_plan_payload(**overrides) -> dict:
    defaults = {"plan_year": 2027}
    defaults.update(overrides)
    return defaults


def labor_entry_payload(**overrides) -> dict:
    defaults = {
        "work_date": "2026-08-02",
        "shift_type": "AM",
        "hours": 1,
    }
    defaults.update(overrides)
    return defaults
