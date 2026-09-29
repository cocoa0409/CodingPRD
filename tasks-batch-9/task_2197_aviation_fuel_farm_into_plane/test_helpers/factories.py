"""Payload factories — one per entity, input fields only."""
import itertools
import random
import string

from .constants import TEST_DEFAULTS

_counter = itertools.count(1)


def _uniq(prefix: str) -> str:
    return f"{prefix}-{next(_counter)}-{random.randint(1000, 999999)}"


_IATA_LETTERS = string.ascii_uppercase


def unique_iata_code() -> str:
    """Exactly three uppercase letters, unique across farms in a test run."""
    return "".join(random.choice(_IATA_LETTERS) for _ in range(3))


def unique_airline_iata_code() -> str:
    """Exactly two uppercase alphanumeric characters."""
    alphabet = string.ascii_uppercase + string.digits
    return "".join(random.choice(alphabet) for _ in range(2))


def create_fuel_farm_payload(**overrides) -> dict:
    payload = {
        "iata_code": unique_iata_code(),
        "name": "Test Consortium Farm",
    }
    payload.update(overrides)
    return payload


def create_environmental_permit_payload(**overrides) -> dict:
    payload = {
        "permit_number": _uniq("PERMIT"),
        "valid_from_utc": "2026-01-01T00:00:00Z",
        "valid_until_utc": "2027-01-01T00:00:00Z",
        "max_daily_throughput_liters": TEST_DEFAULTS["PERMIT_MAX_DAILY_THROUGHPUT"],
    }
    payload.update(overrides)
    return payload


def create_storage_tank_payload(**overrides) -> dict:
    payload = {
        "tank_code": _uniq("TK"),
        "capacity_liters": TEST_DEFAULTS["TANK_CAPACITY_LITERS"],
        "safe_fill_liters": TEST_DEFAULTS["TANK_SAFE_FILL_LITERS"],
        "density_kg_per_m3": TEST_DEFAULTS["TANK_DENSITY"],
    }
    payload.update(overrides)
    return payload


def create_fuel_receipt_payload(storage_tank_id: str, **overrides) -> dict:
    payload = {
        "storage_tank_id": storage_tank_id,
        "delivery_mode": "TRUCK",
        "supplier_name": "Test Supplier",
        "meter_ticket_number": _uniq("MT"),
        "meter_ticket_gross_liters": 10_000.0,
        "tank_opening_gauge_liters": 0.0,
        "tank_closing_gauge_liters": 10_000.0,
        "temperature_c": 15.0,
        "certificate_density_kg_per_m3": 800.0,
    }
    payload.update(overrides)
    return payload


def create_test_results_payload(**overrides) -> dict:
    """An all-passing metric set; override individual metrics to force a FAIL."""
    payload = {
        "water_reaction_rating": 1,
        "particulate_mg_per_l": 0.5,
        "conductivity_ps_per_m": 200.0,
        "observed_density_kg_per_m3": 800.0,
        "flash_point_c": 45.0,
    }
    payload.update(overrides)
    return payload


def create_fueling_asset_payload(**overrides) -> dict:
    payload = {
        "asset_code": _uniq("AS"),
        "asset_type": "TRUCK",
        "tank_capacity_liters": 40_000.0,
    }
    payload.update(overrides)
    return payload


def create_hydrant_cart_payload(**overrides) -> dict:
    payload = {
        "asset_code": _uniq("CART"),
        "asset_type": "HYDRANT_CART",
        "tank_capacity_liters": 0.0,
    }
    payload.update(overrides)
    return payload


def create_filter_change_payload(**overrides) -> dict:
    payload = {
        "element_lot_number": _uniq("LOT"),
        "element_count": 6,
        "post_change_differential_pressure_kpa": 10.0,
    }
    payload.update(overrides)
    return payload


def create_hydrant_pit_payload(source_storage_tank_id: str, **overrides) -> dict:
    payload = {
        "pit_code": _uniq("PIT"),
        "stand_code": "A12",
        "source_storage_tank_id": source_storage_tank_id,
    }
    payload.update(overrides)
    return payload


def create_airline_account_payload(**overrides) -> dict:
    payload = {
        "airline_iata_code": unique_airline_iata_code(),
        "legal_name": "Test Airways Limited",
        "contract_type": "CONTRACT_FUEL",
        "base_price_cents_per_liter": TEST_DEFAULTS["BASE_PRICE_CENTS_PER_LITER"],
        "credit_limit_cents": TEST_DEFAULTS["CREDIT_LIMIT_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_flight_payload(airline_account_id: str, **overrides) -> dict:
    payload = {
        "airline_account_id": airline_account_id,
        "flight_number": _uniq("FL"),
        "tail_number": _uniq("TAIL"),
        "scheduled_departure_utc": "2026-08-01T12:00:00Z",
        "stand_code": "A12",
    }
    payload.update(overrides)
    return payload


def create_fuel_authorization_payload(airline_account_id: str, flight_id: str,
                                     **overrides) -> dict:
    payload = {
        "airline_account_id": airline_account_id,
        "flight_id": flight_id,
        "max_authorized_liters": 20_000.0,
    }
    payload.update(overrides)
    return payload


def create_fueling_order_payload(flight_id: str, fuel_authorization_id: str,
                                 storage_tank_id: str, quoted_authorization_code: str,
                                 **overrides) -> dict:
    payload = {
        "flight_id": flight_id,
        "fuel_authorization_id": fuel_authorization_id,
        "storage_tank_id": storage_tank_id,
        "delivery_mode": "TRUCK",
        "requested_uplift_liters": 10_000.0,
        "window_start_utc": "2026-08-01T10:00:00Z",
        "window_end_utc": "2026-08-01T11:00:00Z",
        "quoted_authorization_code": quoted_authorization_code,
    }
    payload.update(overrides)
    return payload


def create_uplift_record_payload(expected_fueling_order_version: int, **overrides) -> dict:
    payload = {
        "ticket_number": _uniq("UT"),
        "meter_start_liters": 0.0,
        "meter_end_liters": 10_000.0,
        "temperature_c": 15.0,
        "expected_fueling_order_version": expected_fueling_order_version,
    }
    payload.update(overrides)
    return payload


def create_spill_incident_payload(fuel_farm_id: str, **overrides) -> dict:
    payload = {
        "fuel_farm_id": fuel_farm_id,
        "spilled_volume_liters": 5.0,
        "surface": "APRON",
    }
    payload.update(overrides)
    return payload


def create_reconciliation_run_payload(**overrides) -> dict:
    payload = {
        "period_start_utc": "2026-08-01T00:00:00Z",
        "period_end_utc": "2026-08-02T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_invoice_payload(airline_account_id: str, expected_airline_account_version: int,
                           **overrides) -> dict:
    payload = {
        "airline_account_id": airline_account_id,
        "period_start_utc": "2026-08-01T00:00:00Z",
        "period_end_utc": "2026-09-01T00:00:00Z",
        "expected_airline_account_version": expected_airline_account_version,
    }
    payload.update(overrides)
    return payload


def create_gauge_measurement_payload(**overrides) -> dict:
    payload = {
        "measured_volume_liters": 10_000.0,
        "temperature_c": 15.0,
        "water_bottom_mm": 1.0,
    }
    payload.update(overrides)
    return payload
