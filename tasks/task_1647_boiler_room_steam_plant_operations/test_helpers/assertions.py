"""Entity assertions and domain invariant checkers (PRD §2.5, §2.10, §3)."""
import pytest

from prd_bench_local_runner.testing import (
    assert_cost_precision,
    is_iso8601_timestamp,
    is_valid_uuid,
)


def assert_plant(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at ISO 8601"
    assert isinstance(data.get("version"), int), "version must be int"
    assert data["state_code"] in ["MA", "NY", "CA", "TX"]
    assert data["posture"] in ["NORMAL", "DEGRADED", "EMERGENCY"]
    assert isinstance(data.get("ops_run_index"), int)


def assert_boiler(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at ISO 8601"
    assert isinstance(data.get("version"), int), "version must be int"
    assert data["ops_status"] in [
        "STANDBY", "WARMING", "ONLINE", "BANKING", "TRIPPED", "DECOMMISSIONED",
    ]
    assert data["cert_status"] in ["VALID", "EXPIRING", "LAPSED", "SUSPENDED"]
    assert data["water_status"] in ["IN_SPEC", "OUT_OF_SPEC", "CRITICAL"]


def assert_operator(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at ISO 8601"
    assert data["license_class"] in ["CLASS_1", "CLASS_2", "CLASS_3"]
    assert data["license_status"] in ["ACTIVE", "EXPIRING", "EXPIRED", "REVOKED"]


def assert_log_entry(data: dict):
    """Append-only record (PRD §2.5): id + created_at only — no updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at ISO 8601"
    assert "updated_at" not in data, "append-only record must not expose updated_at"
    assert "version" not in data, "append-only record must not expose version"
    assert data["status"] in ["DRAFT", "VERIFIED", "VOIDED"]


def assert_chemistry_log(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at ISO 8601"
    assert "updated_at" not in data, "append-only record must not expose updated_at"
    assert "version" not in data, "append-only record must not expose version"
    assert data["status"] in ["RECORDED", "VOIDED"]


def assert_inspection(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at ISO 8601"
    assert isinstance(data.get("version"), int), "version must be int"
    assert data["inspection_kind"] in [
        "ANNUAL_INTERNAL", "ANNUAL_EXTERNAL", "RELIEF_VALVE_POP", "POST_INCIDENT",
    ]
    assert data["outcome"] in ["PENDING", "PASSED", "FAILED", "CONDITIONAL"]


def assert_steam_trap(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at ISO 8601"
    assert isinstance(data.get("version"), int), "version must be int"
    assert data["condition"] in [
        "UNKNOWN", "OK", "LEAKING", "FAILED_OPEN", "FAILED_CLOSED", "COLD",
    ]
    assert data["status"] in ["IN_SERVICE", "ISOLATED", "REPLACED"]


def assert_load_dispatch(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at ISO 8601"
    assert isinstance(data.get("version"), int), "version must be int"
    assert data["status"] in ["SCHEDULED", "ACTIVE", "COMPLETED", "CANCELLED"]
    assert isinstance(data.get("assigned_boiler_ids"), list)


def assert_incident(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at ISO 8601"
    assert isinstance(data.get("version"), int), "version must be int"
    assert data["severity"] in ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    assert data["kind"] in [
        "OVERPRESSURE", "LOW_WATER", "FLAME_FAILURE",
        "RELIEF_VALVE_LIFT", "CHEMISTRY_EXCURSION", "OTHER",
    ]
    assert data["status"] in ["OPEN", "ACKNOWLEDGED", "MITIGATED", "CLOSED"]


def assert_fuel_delivery(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at ISO 8601"
    assert "updated_at" not in data, "append-only record must not expose updated_at"
    assert "version" not in data, "append-only record must not expose version"


def assert_fuel_ledger_invariant(plant: dict):
    """PRD §2.10: fuel_inventory_gal == total_fuel_received_gal - total_fuel_consumed_gal,
    and it may never go negative."""
    received = plant["total_fuel_received_gal"]
    consumed = plant["total_fuel_consumed_gal"]
    inventory = plant["fuel_inventory_gal"]
    assert inventory == pytest.approx(received - consumed, abs=0.005), (
        f"fuel ledger broken: {received} - {consumed} != {inventory}"
    )
    assert inventory >= 0, f"fuel_inventory_gal must never go negative, got {inventory}"
    assert_cost_precision(inventory)


def assert_water_mass_balance(boiler: dict, tolerance: float = 25.0):
    """PRD §2.10: total_feedwater_gal == total_blowdown_gal + total_steam_lb / 8.345
    within the drift tolerance."""
    rhs = boiler["total_blowdown_gal"] + boiler["total_steam_lb"] / 8.345
    drift = abs(boiler["total_feedwater_gal"] - rhs)
    assert drift <= tolerance + 0.01, (
        f"water mass balance drift {drift} gal exceeds tolerance {tolerance}"
    )
