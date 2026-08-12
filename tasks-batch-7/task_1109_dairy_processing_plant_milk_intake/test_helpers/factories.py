"""Payload factories — one per entity, input fields only (PRD §3)."""
import itertools

from .constants import (
    DEFAULT_CLOCK_ISO,
    PERIOD_END_ISO,
    PERIOD_START_ISO,
    POOL_MONTH,
    POOL_PRICES,
)

_counter = itertools.count(1)


def _next(prefix: str) -> str:
    return f"{prefix}-{next(_counter):04d}"


def create_producer_payload(**overrides) -> dict:
    defaults = {
        "producer_code": _next("P"),
        "farm_name": "Test Farm",
        "base_hauling_rate_cents_per_cwt": 100,
    }
    defaults.update(overrides)
    return defaults


def create_hauler_payload(**overrides) -> dict:
    defaults = {
        "hauler_code": _next("H"),
        "company_name": "Test Hauling Co",
        "license_expires_at": "2027-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_tanker_receipt_payload(producer_id: str, hauler_id: str, **overrides) -> dict:
    defaults = {
        "producer_id": producer_id,
        "hauler_id": hauler_id,
        "arrived_at": "2026-05-05T08:00:00Z",
        "gross_weight_lbs": 50000,
        "tare_weight_lbs": 30000,
        "temperature_f": 40,
    }
    defaults.update(overrides)
    return defaults


def create_lab_test_payload(**overrides) -> dict:
    defaults = {
        "test_type": "ANTIBIOTIC",
        "result_value": 0,
        "lab_technician_id": "lab-001",
    }
    defaults.update(overrides)
    return defaults


def create_component_assay_payload(**overrides) -> dict:
    defaults = {
        "butterfat_pct": 4.00,
        "protein_pct": 3.20,
        "other_solids_pct": 5.70,
    }
    defaults.update(overrides)
    return defaults


def create_settlement_payload(**overrides) -> dict:
    defaults = {
        "period_start_date": PERIOD_START_ISO,
        "period_end_date": PERIOD_END_ISO,
    }
    defaults.update(overrides)
    return defaults


def create_pasteurizer_run_payload(**overrides) -> dict:
    defaults = {
        "pasteurizer_id": "HTST-1",
        "scheduled_start_at": "2026-05-10T08:00:00Z",
        "scheduled_end_at": "2026-05-10T12:00:00Z",
        "flow_rate_gph": 5000,
        "min_hold_temp_f": 161,
    }
    defaults.update(overrides)
    return defaults


def create_cip_cycle_payload(**overrides) -> dict:
    defaults = {
        "started_at": "2026-05-10T06:00:00Z",
        "caustic_conductivity_ms": 90.0,
        "rinse_ph": 7.0,
    }
    defaults.update(overrides)
    return defaults


def create_batch_payload(**overrides) -> dict:
    defaults = {
        "product_code": "WHOLE_MILK",
        "quantity_gallons": 1000,
        "shelf_life_days": 14,
    }
    defaults.update(overrides)
    return defaults


def create_distribution_route_payload(**overrides) -> dict:
    defaults = {
        "route_code": _next("R"),
        "destination_zip": "90210",
        "transit_days": 1,
        "min_days_of_code_required": 5,
    }
    defaults.update(overrides)
    return defaults


def create_grade_a_permit_payload(**overrides) -> dict:
    defaults = {
        "permit_number": _next("GA"),
        "issued_at": "2026-01-01T00:00:00Z",
        "expires_at": "2027-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_pool_payload(**overrides) -> dict:
    defaults = {"pool_month": POOL_MONTH}
    defaults.update(POOL_PRICES)
    defaults.update(overrides)
    return defaults


def create_clock_payload(to_iso8601: str = DEFAULT_CLOCK_ISO) -> dict:
    return {"to_iso8601": to_iso8601}
