"""Payload factories — one per entity, input fields only (PRD §3)."""
import itertools

from .constants import TEST_DEFAULTS

_counter = itertools.count(1)


def _seq(prefix: str) -> str:
    return f"{prefix}-{next(_counter)}"


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "name": _seq("Customer"),
        "credit_limit_cents": TEST_DEFAULTS["CREDIT_LIMIT_CENTS"],
        "minimum_run_units": TEST_DEFAULTS["MINIMUM_RUN_UNITS"],
        "pallet_deposit_cents": TEST_DEFAULTS["PALLET_DEPOSIT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_formula_payload(customer_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "formula_code": _seq("F"),
        "name": _seq("Juice"),
        "target_brix": 12.0,
        "brix_tolerance": 0.3,
        "process_type": "PASTEURIZATION",
        "container_fill_ml": 473,
        "concentrate_brix": 65.0,
        "allergen_group": "NONE",
        "shelf_life_days": 120,
        "claims": ["ORGANIC"],
    }
    defaults.update(overrides)
    return defaults


def create_tank_payload(**overrides) -> dict:
    defaults = {
        "tank_code": _seq("T"),
        "capacity_liters": TEST_DEFAULTS["TANK_CAPACITY_LITERS"],
    }
    defaults.update(overrides)
    return defaults


def create_batch_payload(formula_id: str, tank_id: str, **overrides) -> dict:
    defaults = {
        "formula_id": formula_id,
        "tank_id": tank_id,
        "planned_start_at": "2026-08-10T08:00:00Z",
        "planned_end_at": "2026-08-10T12:00:00Z",
        "quantity_liters": TEST_DEFAULTS["BATCH_QUANTITY_LITERS"],
    }
    defaults.update(overrides)
    return defaults


def create_process_run_payload(batch_id: str, process_type: str = "PASTEURIZATION", **overrides) -> dict:
    defaults: dict = {"batch_id": batch_id}
    if process_type == "PASTEURIZATION":
        defaults["setpoint_temp_c"] = 88.0
        defaults["setpoint_hold_seconds"] = 30
    else:
        defaults["setpoint_pressure_mpa"] = 600.0
        defaults["setpoint_pressure_hold_seconds"] = 180
    defaults.update(overrides)
    return defaults


def complete_process_run_payload(process_type: str = "PASTEURIZATION", **overrides) -> dict:
    """Exact-setpoint readings -> VALIDATED / deviation NONE."""
    if process_type == "PASTEURIZATION":
        defaults: dict = {"min_temp_c": 88.0, "time_below_setpoint_seconds": 0}
    else:
        defaults = {"min_pressure_mpa": 600.0, "pressure_hold_shortfall_seconds": 0}
    defaults.update(overrides)
    return defaults


def create_container_lot_payload(**overrides) -> dict:
    defaults = {
        "container_type": "PET_473",
        "quantity_received": TEST_DEFAULTS["CONTAINER_LOT_QTY"],
        "supplier_lot_code": _seq("SUP"),
    }
    defaults.update(overrides)
    return defaults


def create_line_payload(**overrides) -> dict:
    defaults = {
        "line_code": _seq("L"),
        "supported_container_types": ["PET_473"],
        "nominal_cpm": 200,
    }
    defaults.update(overrides)
    return defaults


def create_production_run_payload(customer_id: str, formula_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "formula_id": formula_id,
        "container_type": "PET_473",
        "planned_units": TEST_DEFAULTS["PLANNED_UNITS"],
        "unit_price_cents": TEST_DEFAULTS["UNIT_PRICE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def schedule_run_payload(batch_id: str, line_id: str, expected_version: int, **overrides) -> dict:
    defaults = {
        "batch_id": batch_id,
        "line_id": line_id,
        "scheduled_start_at": "2026-08-11T08:00:00Z",
        "scheduled_end_at": "2026-08-11T12:00:00Z",
        "expected_production_run_version": expected_version,
    }
    defaults.update(overrides)
    return defaults


def complete_run_payload(warehouse_zone_id: str, **overrides) -> dict:
    defaults = {
        "actual_units_filled": 1000,
        "avg_fill_ml": 473,
        "warehouse_zone_id": warehouse_zone_id,
    }
    defaults.update(overrides)
    return defaults


def create_zone_payload(**overrides) -> dict:
    defaults = {
        "zone_code": _seq("Z"),
        "temperature_class": "AMBIENT",
        "pallet_capacity": TEST_DEFAULTS["PALLET_CAPACITY"],
    }
    defaults.update(overrides)
    return defaults


def create_shipment_order_payload(customer_id: str, formula_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "formula_id": formula_id,
        "channel": "FOODSERVICE",
        "requested_delivery_date": "2026-08-20",
        "units_requested": 500,
    }
    defaults.update(overrides)
    return defaults
