"""Payload factories — one per entity, input fields only."""
import itertools

from .constants import SEDAN_POLICY

_counter = itertools.count(1)


def _uniq(prefix: str) -> str:
    return f"{prefix}-{next(_counter)}"


def create_vehicle_payload(**overrides) -> dict:
    defaults = {
        "vin": _uniq("VIN"),
        "vehicle_class": "SEDAN",
        "acquisition_cost_cents": 2000000,
        "in_service_date": "2024-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_department_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Department",
        "cost_center_code": _uniq("CC"),
        "monthly_budget_cents": 10000000,
    }
    defaults.update(overrides)
    return defaults


def create_vehicle_class_policy_payload(**overrides) -> dict:
    defaults = dict(SEDAN_POLICY)
    defaults.update(overrides)
    return defaults


def create_reservation_payload(department_id, **overrides) -> dict:
    defaults = {
        "department_id": department_id,
        "requested_start": "2026-06-05T09:00:00Z",
        "requested_end": "2026-06-05T13:00:00Z",
        "driver_name": "Test Driver",
        "purpose": "field work",
    }
    defaults.update(overrides)
    return defaults


def create_shop_bay_payload(**overrides) -> dict:
    defaults = {
        "name": _uniq("Bay"),
        "bay_type": "GENERAL",
    }
    defaults.update(overrides)
    return defaults


def create_work_order_payload(vehicle_id, bay_id, **overrides) -> dict:
    defaults = {
        "vehicle_id": vehicle_id,
        "bay_id": bay_id,
        "wo_type": "REPAIR",
        "scheduled_start": "2026-06-02T09:00:00Z",
        "scheduled_end": "2026-06-02T11:00:00Z",
        "labor_rate_cents": 100,
    }
    defaults.update(overrides)
    return defaults


def create_fuel_log_payload(**overrides) -> dict:
    defaults = {
        "reading_at": "2026-03-02T00:00:00Z",
        "gallons": 10,
        "fuel_cost_cents": 0,
        "odometer_miles": 0,
    }
    defaults.update(overrides)
    return defaults


def create_accident_claim_payload(vehicle_id, **overrides) -> dict:
    defaults = {
        "vehicle_id": vehicle_id,
        "reported_at": "2026-03-05T00:00:00Z",
        "at_fault": False,
        "estimated_damage_cents": 100000,
    }
    defaults.update(overrides)
    return defaults


def create_disposal_payload(expected_vehicle_version, **overrides) -> dict:
    defaults = {
        "reserve_price_cents": 100000,
        "expected_vehicle_version": expected_vehicle_version,
    }
    defaults.update(overrides)
    return defaults


def create_chargeback_invoice_payload(period_start, period_end, expected_department_version, **overrides) -> dict:
    defaults = {
        "period_start": period_start,
        "period_end": period_end,
        "expected_department_version": expected_department_version,
    }
    defaults.update(overrides)
    return defaults
