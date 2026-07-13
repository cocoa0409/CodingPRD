"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_beach(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["town_code"], str) and len(data["town_code"]) > 0
    assert isinstance(data["season_start_date"], str)
    assert isinstance(data["season_end_date"], str)


def assert_zone(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["beach_id"])
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["min_guards_required"], int)
    assert data["flag_status"] in ("GREEN", "YELLOW", "RED", "BLACK")
    assert data["water_status"] in ("OPEN", "CLOSED")
    assert data["rip_current_level"] in ("LOW", "MODERATE", "HIGH")
    assert isinstance(data["on_duty_guard_count"], int)


def assert_tower(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["zone_id"])
    assert isinstance(data["label"], str) and len(data["label"]) > 0
    assert isinstance(data["max_concurrent_guards"], int)
    assert data["status"] in ("OPEN", "OFFLINE")


def assert_lifeguard(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["beach_id"])
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["certification_level"] in ("JUNIOR", "SENIOR", "CAPTAIN")
    assert isinstance(data["employee_ref"], str)


def assert_shift(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["lifeguard_id"])
    assert is_valid_uuid(data["tower_id"])
    assert isinstance(data["scheduled_start"], str)
    assert isinstance(data["scheduled_end"], str)
    assert data["status"] in ("SCHEDULED", "ON_DUTY", "ON_BREAK", "OFF_DUTY", "CANCELLED")


def assert_incident(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["zone_id"])
    assert data["type"] in ("RESCUE", "MEDICAL", "LOST_CHILD", "FIRST_AID")
    assert data["severity"] in ("LOW", "MODERATE", "CRITICAL")
    assert isinstance(data["victim_count"], int)
    assert data["status"] in (
        "OPEN", "RESOLVED_ON_SCENE", "ESCALATED_EMS", "REUNITED", "CLOSED",
    )


def assert_advisory(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["zone_id"])
    assert data["basis"] in ("SINGLE_SAMPLE", "GEOMEAN_30DAY")
    assert data["level"] in ("NONE", "ADVISORY", "CLOSURE")
    assert data["status"] in ("ACTIVE", "SUPERSEDED", "LIFTED")


def assert_parking_lot(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["beach_id"])
    assert isinstance(data["total_spaces"], int)
    assert isinstance(data["available_spaces"], int)
    assert isinstance(data["daily_rate_cents"], int)
    assert data["available_spaces"] <= data["total_spaces"]


def assert_parking_pass(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["lot_id"])
    assert data["vehicle_type"] in ("CAR", "OVERSIZED")
    assert data["pass_type"] in ("DAILY", "SEASON")
    assert isinstance(data["fee_cents"], int)
    assert data["status"] in ("ACTIVE", "REVOKED")


def assert_water_quality_sample(data: dict):
    """Append-only event record: id + created_at only, no version / updated_at (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data["zone_id"])
    assert isinstance(data["enterococci_mpn"], int)
