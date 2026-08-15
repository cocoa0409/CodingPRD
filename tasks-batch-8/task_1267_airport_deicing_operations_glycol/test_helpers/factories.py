"""Payload factories — one per entity, input fields only."""
from typing import Optional

# ---------------------------------------------------------------------------
# Defaults used across test setups. Values are picked to be large enough to
# avoid tripping the fiscal gate or tank thresholds unless a test intends it.
# ---------------------------------------------------------------------------

DEFAULTS = {
    "STATION_CODE": "ST1",
    "STATION_NAME": "Station One",
    "PAD_CODE": "P1",
    "PAD_RATED_COLLECTION_PCT": 60.0,
    "AIRLINE_CODE": "AA",
    "AIRLINE_NAME": "Air",
    "AIRLINE_CREDIT_LIMIT_CENTS": 10_000_000,
    "TANK_CAPACITY_LITERS": 50_000,
    "TANK_ON_HAND_LITERS": 20_000,
    "TANK_REORDER_THRESHOLD_LITERS": 300,
    "PERMIT_MAX_SINGLE_READING_MG_L": 100,
    "PERMIT_ROLLING_WINDOW_DAYS": 7,
    "PERMIT_ROLLING_WINDOW_MAX_LITERS": 100_000,
    "WEATHER_STARTED_AT": "2026-05-01T00:00:00Z",
    "PERMIT_EFFECTIVE_FROM": "2026-01-01T00:00:00Z",
    "PERMIT_EFFECTIVE_TO": "2026-12-31T00:00:00Z",
    "SCHEDULED_DEPARTURE": "2026-05-01T12:00:00Z",
    "WINDOW_START": "2026-05-01T10:00:00Z",
    "WINDOW_END": "2026-05-01T10:30:00Z",
    "SPILL_OCCURRED_AT": "2026-05-01T00:00:00Z",
    "RECYCLE_VENDOR": "ReGlycol",
    "RECYCLE_MIN_CONCENTRATION_PCT": 40,
    "RECYCLE_PRICE_PER_LITER_CENTS": 12,
    "RECYCLE_CONTRACTED_MIN_LITERS": 300,
}


def create_station_payload(**overrides) -> dict:
    defaults = {
        "code": DEFAULTS["STATION_CODE"],
        "name": DEFAULTS["STATION_NAME"],
    }
    defaults.update(overrides)
    return defaults


def create_pad_payload(station_id: str, **overrides) -> dict:
    defaults = {
        "station_id": station_id,
        "code": DEFAULTS["PAD_CODE"],
        "max_size_class": "LARGE",
        "rated_collection_pct": DEFAULTS["PAD_RATED_COLLECTION_PCT"],
    }
    defaults.update(overrides)
    return defaults


def create_weather_event_payload(station_id: str, **overrides) -> dict:
    defaults = {
        "station_id": station_id,
        "precip_type": "SNOW",
        "precip_rate": "LIGHT",
        "severity": "LEVEL_1",
        "started_at": DEFAULTS["WEATHER_STARTED_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_fluid_tank_payload(station_id: str, **overrides) -> dict:
    defaults = {
        "station_id": station_id,
        "fluid_type": "TYPE_I",
        "concentration_pct": 100,
        "capacity_liters": DEFAULTS["TANK_CAPACITY_LITERS"],
        "on_hand_liters": DEFAULTS["TANK_ON_HAND_LITERS"],
        "reorder_threshold_liters": DEFAULTS["TANK_REORDER_THRESHOLD_LITERS"],
    }
    defaults.update(overrides)
    return defaults


def create_airline_payload(**overrides) -> dict:
    defaults = {
        "code": DEFAULTS["AIRLINE_CODE"],
        "name": DEFAULTS["AIRLINE_NAME"],
        "credit_limit_cents": DEFAULTS["AIRLINE_CREDIT_LIMIT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_deice_request_payload(airline_id: str, station_id: str, **overrides) -> dict:
    defaults = {
        "airline_id": airline_id,
        "station_id": station_id,
        "flight_number": "AA1",
        "aircraft_type": "A320",
        "size_class": "MEDIUM",
        "scheduled_departure": DEFAULTS["SCHEDULED_DEPARTURE"],
        "fluid_type": "TYPE_I",
    }
    defaults.update(overrides)
    return defaults


def assign_request_payload(pad_id: str, **overrides) -> dict:
    defaults = {
        "pad_id": pad_id,
        "window_start": DEFAULTS["WINDOW_START"],
        "window_end": DEFAULTS["WINDOW_END"],
    }
    defaults.update(overrides)
    return defaults


def create_inspection_payload(operation_id: str, **overrides) -> dict:
    defaults = {
        "operation_id": operation_id,
        "kind": "ACCEPTANCE",
        "result": "PASS",
    }
    defaults.update(overrides)
    return defaults


def create_discharge_permit_payload(station_id: str, **overrides) -> dict:
    defaults = {
        "station_id": station_id,
        "permit_number": "P-1",
        "effective_from": DEFAULTS["PERMIT_EFFECTIVE_FROM"],
        "effective_to": DEFAULTS["PERMIT_EFFECTIVE_TO"],
        "max_single_reading_mg_l": DEFAULTS["PERMIT_MAX_SINGLE_READING_MG_L"],
        "rolling_window_days": DEFAULTS["PERMIT_ROLLING_WINDOW_DAYS"],
        "rolling_window_max_liters": DEFAULTS["PERMIT_ROLLING_WINDOW_MAX_LITERS"],
    }
    defaults.update(overrides)
    return defaults


def create_effluent_reading_payload(**overrides) -> dict:
    defaults = {
        "measured_at": "2026-05-01T00:00:00Z",
        "concentration_mg_l": 10,
        "volume_liters": 10,
    }
    defaults.update(overrides)
    return defaults


def create_spill_report_payload(station_id: str, tank_id: str, **overrides) -> dict:
    defaults = {
        "station_id": station_id,
        "tank_id": tank_id,
        "quantity_liters": 20,
        "occurred_at": DEFAULTS["SPILL_OCCURRED_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_recycling_contract_payload(station_id: str, **overrides) -> dict:
    defaults = {
        "station_id": station_id,
        "vendor_name": DEFAULTS["RECYCLE_VENDOR"],
        "min_concentration_pct": DEFAULTS["RECYCLE_MIN_CONCENTRATION_PCT"],
        "price_per_liter_cents": DEFAULTS["RECYCLE_PRICE_PER_LITER_CENTS"],
        "contracted_min_liters": DEFAULTS["RECYCLE_CONTRACTED_MIN_LITERS"],
    }
    defaults.update(overrides)
    return defaults


def record_shipment_payload(**overrides) -> dict:
    defaults = {
        "volume_liters": 100,
        "concentration_pct": 55,
    }
    defaults.update(overrides)
    return defaults


def create_invoice_payload(operation_id: str, expected_airline_version: int, **overrides) -> dict:
    defaults = {
        "operation_id": operation_id,
        "expected_airline_version": expected_airline_version,
    }
    defaults.update(overrides)
    return defaults


def replenish_payload(liters: float, **overrides) -> dict:
    defaults = {"liters": liters}
    defaults.update(overrides)
    return defaults


def escalate_payload(assigned_crew_count: int, **overrides) -> dict:
    defaults = {"assigned_crew_count": assigned_crew_count}
    defaults.update(overrides)
    return defaults


def start_operation_payload(oat_celsius: float, **overrides) -> dict:
    defaults = {"oat_celsius": oat_celsius}
    defaults.update(overrides)
    return defaults


def complete_operation_payload(actual_liters: float, collected_liters: float, **overrides) -> dict:
    defaults = {
        "actual_liters": actual_liters,
        "collected_liters": collected_liters,
    }
    defaults.update(overrides)
    return defaults
