"""Payload factories — one per entity, input fields only (PRD §3, §4)."""
from .constants import TEST_DEFAULTS


def create_driver_payload(**overrides) -> dict:
    defaults = {
        "cdl_number": "CDL-1000",
        "full_name": "Test Driver",
        "home_terminal": "DAL",
        "pay_model": "MILEAGE",
        "pay_rate_cents_per_mile": TEST_DEFAULTS["PAY_RATE_CENTS_PER_MILE"],
        "hired_at": "2025-01-01T00:00:00Z",
        "last_home_at": "2026-07-28T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_tractor_payload(**overrides) -> dict:
    defaults = {
        "unit_number": "T-1000",
        "home_terminal": "DAL",
        "odometer_miles": TEST_DEFAULTS["ODOMETER_MILES"],
        "current_state_code": "TX",
        "tank_capacity_gallons": TEST_DEFAULTS["TANK_CAPACITY_GALLONS"],
        "current_fuel_gallons": TEST_DEFAULTS["CURRENT_FUEL_GALLONS"],
    }
    defaults.update(overrides)
    return defaults


def create_customer_payload(**overrides) -> dict:
    defaults = {"name": "Acme Foods"}
    defaults.update(overrides)
    return defaults


def create_lane_payload(**overrides) -> dict:
    defaults = {
        "origin_state": "TX",
        "destination_state": "GA",
        "loaded_miles": TEST_DEFAULTS["LOADED_MILES"],
        "rpm_floor_cents": TEST_DEFAULTS["RPM_FLOOR_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_state_fuel_rate_payload(**overrides) -> dict:
    defaults = {
        "state_code": "US-NATIONAL",
        "tax_cents_per_gallon": 0,
        "avg_pump_price_cents": TEST_DEFAULTS["NATIONAL_PUMP_CENTS"],
        "effective_from": "2026-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_load_payload(customer_id: str, lane_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "lane_id": lane_id,
        "rate_cents": TEST_DEFAULTS["RATE_CENTS"],
        "weight_lbs": TEST_DEFAULTS["WEIGHT_LBS"],
        "pickup_appt_at": "2026-08-02T08:00:00Z",
        "delivery_appt_at": "2026-08-03T18:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_trip_payload(load_id: str, driver_id: str, tractor_id: str,
                        **overrides) -> dict:
    defaults = {
        "load_id": load_id,
        "driver_id": driver_id,
        "tractor_id": tractor_id,
        "planned_deadhead_miles": TEST_DEFAULTS["PLANNED_DEADHEAD_MILES"],
        "planned_start_at": "2026-08-02T06:00:00Z",
        "route_states": [{"state_code": "TX", "miles": 1020}],
    }
    defaults.update(overrides)
    return defaults


def create_duty_event_payload(**overrides) -> dict:
    defaults = {
        "event_type": "OFF_DUTY",
        "occurred_at": "2026-08-01T06:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_check_call_payload(**overrides) -> dict:
    defaults = {
        "kind": "EN_ROUTE",
        "occurred_at": "2026-08-02T12:00:00Z",
        "state_code": "TX",
        "odometer_miles": 100100,
    }
    defaults.update(overrides)
    return defaults


def create_accessorial_payload(**overrides) -> dict:
    defaults = {
        "type": "LUMPER",
        "quantity": 3013,
    }
    defaults.update(overrides)
    return defaults


def create_fuel_purchase_payload(driver_id: str, **overrides) -> dict:
    defaults = {
        "driver_id": driver_id,
        "state_code": "TX",
        "gallons": 10,
        "pump_price_cents": 400,
        "purchased_at": "2026-08-02T12:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_safety_event_payload(**overrides) -> dict:
    defaults = {
        "kind": "INSPECTION_VIOLATION",
        "severity_points": 10,
        "occurred_at": "2026-07-15T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_settlement_payload(driver_id: str, **overrides) -> dict:
    defaults = {
        "driver_id": driver_id,
        "period_start": "2026-08-01T00:00:00Z",
        "period_end": "2026-08-08T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults
