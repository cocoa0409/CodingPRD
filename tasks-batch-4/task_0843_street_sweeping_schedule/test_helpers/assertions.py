"""Entity assertions and domain invariant checkers.

Uses the framework's generic validators (is_valid_uuid, is_iso8601_timestamp)
internally. Every persisted resource carries the common quartet id/created_at/
updated_at/version (PRD §2.4).
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an int"
    assert data["version"] >= 1, "version starts at 1"


def assert_route(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["zone_code"], str) and data["zone_code"]
    assert data["sweep_weekday"] in ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
    assert data["status"] in ["ACTIVE", "INACTIVE"]
    assert isinstance(data["completed_block_count"], int)
    assert data["completed_block_count"] >= 0


def assert_block(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["route_id"])
    assert data["side"] in ["ODD", "EVEN", "BOTH"]
    assert data["sign_status"] in ["UNPOSTED", "POSTED", "VERIFIED"]
    assert isinstance(data["linear_feet"], int) and data["linear_feet"] >= 1
    assert isinstance(data["enforcement_enabled"], bool)
    assert isinstance(data["sign_enforceable"], bool)
    assert isinstance(data["pending_citation_cents"], int)
    assert data["pending_citation_cents"] >= 0


def assert_equipment(data: dict):
    _assert_common(data)
    assert data["type"] in ["MECHANICAL", "REGENERATIVE_AIR", "VACUUM"]
    assert isinstance(data["hopper_capacity_lbs"], int) and data["hopper_capacity_lbs"] >= 1
    assert data["status"] in ["AVAILABLE", "IN_SERVICE"]


def assert_shift(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["equipment_id"])
    assert data["status"] in ["PLANNED", "IN_PROGRESS", "CLOSED"]
    assert isinstance(data["total_debris_lbs"], int)
    assert data["total_debris_lbs"] >= 0
    assert isinstance(data["gross_tonnage"], (int, float))
    assert isinstance(data["net_tonnage"], (int, float))


def assert_sweep_event(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["block_id"])
    assert data["status"] in ["SCHEDULED", "SWEPT", "MISSED", "SUSPENDED", "VOIDED"]
    assert isinstance(data["is_makeup"], bool)
    assert isinstance(data["notified_resident_count"], int)


def assert_suspension(data: dict):
    _assert_common(data)
    assert data["reason"] in ["HOLIDAY", "LEAF_SEASON", "WEATHER", "OTHER"]
    assert data["scope"] in ["SYSTEM", "ROUTE"]
    assert data["status"] in ["SCHEDULED", "ACTIVE", "LIFTED"]
    assert isinstance(data["suspended_event_count"], int)
    assert data["suspended_event_count"] >= 0


def assert_citation(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["block_id"])
    assert isinstance(data["plate"], str) and data["plate"]
    assert data["status"] in ["ISSUED", "CONTESTED", "UPHELD", "DISMISSED", "PAID"]
    assert isinstance(data["amount_due_cents"], int)
    assert data["amount_due_cents"] >= 0
    assert isinstance(data["prior_upheld_count"], int)


def assert_resident(data: dict):
    _assert_common(data)
    assert isinstance(data["email"], str) and data["email"]
    assert is_valid_uuid(data["home_block_id"])
    assert isinstance(data["notify_opt_in"], bool)


def assert_complaint(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["resident_id"])
    assert is_valid_uuid(data["block_id"])
    assert data["category"] in ["MISSED_BLOCK", "DEBRIS_LEFT", "SIGN_DAMAGED", "OTHER"]
    assert data["status"] in ["OPEN", "RESOLVED", "REOPENED", "REJECTED"]
