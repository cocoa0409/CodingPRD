"""Payload factories — one per entity, input fields only (PRD §3)."""
import itertools

from .constants import TEST_DEFAULTS

_counter = itertools.count(1)


def _unique(prefix: str) -> str:
    return f"{prefix}-{next(_counter):04d}"


def create_plant_payload(**overrides) -> dict:
    defaults = {"plant_name": _unique("Plant")}
    defaults.update(overrides)
    return defaults


def create_tank_payload(plant_id: str, **overrides) -> dict:
    defaults = {
        "plant_id": plant_id,
        "product_code": "O2",
        "capacity_liters": TEST_DEFAULTS["TANK_CAPACITY_LITERS"],
        "initial_level_liters": TEST_DEFAULTS["TANK_INITIAL_LEVEL_LITERS"],
        "reorder_point_liters": TEST_DEFAULTS["TANK_REORDER_POINT_LITERS"],
    }
    defaults.update(overrides)
    return defaults


def create_telemetry_reading_payload(**overrides) -> dict:
    defaults = {
        "measured_level_liters": 4900,
        "measured_at": TEST_DEFAULTS.get("MEASURED_AT", "2026-08-01T00:00:00Z"),
        "source": "MANUAL_DIP",
    }
    defaults.update(overrides)
    return defaults


def create_cylinder_payload(**overrides) -> dict:
    defaults = {
        "serial_number": _unique("SN"),
        "size_code": "STANDARD",
        "service_gas": "O2",
        "last_hydro_date": TEST_DEFAULTS["LAST_HYDRO_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_fill_lot_payload(tank_id: str, **overrides) -> dict:
    defaults = {
        "tank_id": tank_id,
        "product_code": "O2",
        "target_fill_pressure_bar": TEST_DEFAULTS["TARGET_FILL_PRESSURE_BAR"],
    }
    defaults.update(overrides)
    return defaults


def fill_lot_analysis_payload(fill_lot_id: str, readings=None, **overrides) -> dict:
    defaults = {
        "subject_type": "FILL_LOT",
        "fill_lot_id": fill_lot_id,
        "readings": readings if readings is not None else [{"analyte": "CO", "reading_ppm": 5}],
    }
    defaults.update(overrides)
    return defaults


def blend_analysis_payload(blend_order_id: str, readings=None, **overrides) -> dict:
    defaults = {
        "subject_type": "BLEND_ORDER",
        "blend_order_id": blend_order_id,
        "readings": readings
        if readings is not None
        else [{"product_code": "O2", "actual_pct": 21.00}, {"product_code": "N2", "actual_pct": 79.00}],
    }
    defaults.update(overrides)
    return defaults


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "account_name": _unique("Customer"),
        "billing_variant": "CALENDAR_DAY",
        "free_days": 0,
        "credit_limit_cents": TEST_DEFAULTS["CREDIT_LIMIT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_rental_payload(customer_id: str, cylinder_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "cylinder_id": cylinder_id,
        "daily_rate_cents": TEST_DEFAULTS["DAILY_RATE_CENTS"],
        "planned_days": 5,
    }
    defaults.update(overrides)
    return defaults


def create_driver_payload(**overrides) -> dict:
    defaults = {
        "driver_name": _unique("Driver"),
        "cdl_class": "A",
        "hazmat_endorsements": [
            {"endorsement_class": "NONFLAMMABLE_GAS", "expiry_date": "2027-01-01"}
        ],
        "medical_card_expiry": "2027-01-01",
    }
    defaults.update(overrides)
    return defaults


def create_route_payload(**overrides) -> dict:
    defaults = {
        "route_date": "2026-08-05",
        "window_start_hour": 8,
        "window_end_hour": 12,
        "stops": [{"stop_name": _unique("Stop"), "hazmat_classes": ["NONFLAMMABLE_GAS"]}],
    }
    defaults.update(overrides)
    return defaults


def create_installation_payload(customer_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "product_code": "O2",
        "capacity_liters": 5000,
        "initial_level_liters": 2000,
        "reorder_point_liters": 400,
        "max_order_qty_liters": 3000,
    }
    defaults.update(overrides)
    return defaults


def create_replenishment_order_payload(
    installation_id: str, scheduled_delivery_at: str, expected_installation_version: int,
    **overrides,
) -> dict:
    defaults = {
        "installation_id": installation_id,
        "scheduled_delivery_at": scheduled_delivery_at,
        "expected_installation_version": expected_installation_version,
    }
    defaults.update(overrides)
    return defaults


# Default "air-like" blend recipe: 21% O2 / 79% N2 (PRD §3.9 examples).
DEFAULT_BLEND_COMPONENTS = [
    {"product_code": "O2", "target_pct": 21.00, "tolerance_pct": 0.50,
     "unit_cost_cents_per_liter": 300},
    {"product_code": "N2", "target_pct": 79.00, "tolerance_pct": 0.50,
     "unit_cost_cents_per_liter": 100},
]


def create_blend_order_payload(customer_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "batch_qty_liters": 1000,
        "components": [dict(c) for c in DEFAULT_BLEND_COMPONENTS],
    }
    defaults.update(overrides)
    return defaults


def create_billing_run_payload(**overrides) -> dict:
    defaults = {"period_start": "2026-08-01", "period_end": "2026-08-10"}
    defaults.update(overrides)
    return defaults
