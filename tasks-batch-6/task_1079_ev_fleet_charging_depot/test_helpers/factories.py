"""Payload factories — one per entity, input fields only."""
from .constants import TEST_DEFAULTS, FLAT_WINDOWS

_vin_seq = [0]


def unique_vin(prefix="VIN"):
    _vin_seq[0] += 1
    return f"{prefix}-{_vin_seq[0]}"


def create_depot_payload(**overrides) -> dict:
    defaults = {
        "name": "Depot D",
        "max_load_kw": TEST_DEFAULTS["MAX_LOAD_KW"],
        "contracted_capacity_kw": TEST_DEFAULTS["CONTRACTED_CAPACITY_KW"],
        "demand_rate_cents_per_kw": TEST_DEFAULTS["DEMAND_RATE"],
        "overage_rate_cents_per_kw": TEST_DEFAULTS["OVERAGE_RATE"],
        "reimbursement_budget_cents": TEST_DEFAULTS["REIMBURSEMENT_BUDGET_CENTS"],
        "tariff_windows": [dict(w) for w in FLAT_WINDOWS],
    }
    defaults.update(overrides)
    return defaults


def create_charger_payload(depot_id, **overrides) -> dict:
    defaults = {
        "depot_id": depot_id,
        "name": "C1",
        "connector_type": "CCS",
        "max_power_kw": 150,
    }
    defaults.update(overrides)
    return defaults


def create_vehicle_payload(depot_id, **overrides) -> dict:
    defaults = {
        "depot_id": depot_id,
        "vin": overrides.pop("vin", unique_vin()),
        "connector_type": "CCS",
        "battery_capacity_kwh": TEST_DEFAULTS["BATTERY_KWH"],
        "efficiency_kwh_per_km": TEST_DEFAULTS["EFFICIENCY_KWH_PER_KM"],
        "current_soc_pct": 50,
    }
    defaults.update(overrides)
    return defaults


def create_driver_payload(depot_id, **overrides) -> dict:
    defaults = {
        "depot_id": depot_id,
        "name": "DR",
        "email": "dr@x.com",
        "home_tariff_cents_per_kwh": TEST_DEFAULTS["HOME_TARIFF"],
    }
    defaults.update(overrides)
    return defaults


def create_session_payload(depot_id, charger_id, vehicle_id, expected_depot_version, **overrides) -> dict:
    defaults = {
        "depot_id": depot_id,
        "charger_id": charger_id,
        "vehicle_id": vehicle_id,
        "scheduled_start": "2026-05-10T10:00:00Z",
        "scheduled_end": "2026-05-10T11:00:00Z",
        "target_soc_pct": 80,
        "power_kw": 100,
        "expected_depot_version": expected_depot_version,
    }
    defaults.update(overrides)
    return defaults


def create_route_payload(depot_id, vehicle_id, driver_id, **overrides) -> dict:
    defaults = {
        "depot_id": depot_id,
        "vehicle_id": vehicle_id,
        "driver_id": driver_id,
        "route_name": "R",
        "distance_km": 100,
        "required_soc_pct": 80,
        "scheduled_departure": "2026-05-12T06:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_work_order_payload(asset_type, **overrides) -> dict:
    defaults = {
        "asset_type": asset_type,
        "issue": "fault",
        "severity": "HIGH",
    }
    defaults.update(overrides)
    return defaults


def create_claim_payload(driver_id, depot_id, expected_depot_version, **overrides) -> dict:
    defaults = {
        "driver_id": driver_id,
        "depot_id": depot_id,
        "period_month": "2026-05",
        "kwh_claimed": 100,
        "odometer_start": 1000,
        "odometer_end": 1500,
        "expected_depot_version": expected_depot_version,
    }
    defaults.update(overrides)
    return defaults


def create_invoice_payload(depot_id, period_month, **overrides) -> dict:
    defaults = {"depot_id": depot_id, "period_month": period_month}
    defaults.update(overrides)
    return defaults
