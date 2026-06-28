"""Entity assertions and domain invariant checkers.

Each assert_{entity}() validates the response structure against the PRD contract,
using the framework's generic format checkers internally. Field names are PRD-exact.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_facility(data: dict):
    assert is_valid_uuid(data.get("id", "")), "facility id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["posture"] in ("OPEN", "RESTRICTED", "CLOSED")
    assert isinstance(data["open_incident_count"], int) and data["open_incident_count"] >= 0
    assert isinstance(data["epoch_index"], int) and data["epoch_index"] >= 0
    assert isinstance(data["token_price_cents"], int) and data["token_price_cents"] >= 1
    assert isinstance(data["hourly_rate_cents"], int) and data["hourly_rate_cents"] >= 0
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_lane(data: dict):
    assert is_valid_uuid(data.get("id", "")), "lane id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["label"], str) and len(data["label"]) > 0
    assert data["kind"] in ("CAGE", "TUNNEL", "LANE")
    assert data["maint_status"] in ("AVAILABLE", "UNDER_MAINTENANCE", "CLOSED")
    assert isinstance(data["buffer_minutes"], int) and data["buffer_minutes"] >= 0
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_machine(data: dict):
    assert is_valid_uuid(data.get("id", "")), "machine id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["model"] in ("WHEEL", "ARM", "SOFT_TOSS")
    assert data["status"] in ("OPERATIONAL", "DEGRADED", "OUT_OF_SERVICE")
    assert isinstance(data["pitch_count"], int) and data["pitch_count"] >= 0
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_maintenance(data: dict):
    assert is_valid_uuid(data.get("id", "")), "maintenance id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["severity"] in ("ROUTINE", "CRITICAL")
    assert data["status"] in ("OPEN", "RESOLVED")
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_member(data: dict):
    assert is_valid_uuid(data.get("id", "")), "member id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["tier"] in ("NONE", "BRONZE", "GOLD")
    assert isinstance(data["token_balance"], int) and data["token_balance"] >= 0
    assert isinstance(data["monthly_member_minutes_used"], int)
    assert data["monthly_member_minutes_used"] >= 0
    assert isinstance(data["no_show_strikes"], int) and data["no_show_strikes"] >= 0
    assert isinstance(data["waiver_ok"], bool)
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_waiver(data: dict):
    """Waiver is append-only: id + created_at only, no updated_at, no version."""
    assert is_valid_uuid(data.get("id", "")), "waiver id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["status"] in ("SIGNED", "VOID")
    assert "version" not in data, "Waiver must not carry a version field"
    assert "updated_at" not in data, "Waiver must not carry an updated_at field"


def assert_instructor(data: dict):
    assert is_valid_uuid(data.get("id", "")), "instructor id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["rate_cents_per_hour"], int) and data["rate_cents_per_hour"] >= 0
    assert isinstance(data["active"], bool)
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_booking(data: dict):
    assert is_valid_uuid(data.get("id", "")), "booking id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["kind"] in ("OPEN_SLOT", "LESSON", "TEAM_BLOCK", "PARTY")
    assert data["pay_mode"] in ("TOKEN", "HOURLY", "MEMBERSHIP")
    assert data["status"] in (
        "REQUESTED", "CONFIRMED", "CHECKED_IN", "COMPLETED",
        "CANCELLED", "REJECTED", "NO_SHOW",
    )
    assert isinstance(data["duration_minutes"], int) and data["duration_minutes"] > 0
    assert isinstance(data["quoted_cost_cents"], int) and data["quoted_cost_cents"] >= 0
    assert isinstance(data["final_cost_cents"], int) and data["final_cost_cents"] >= 0
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_program(data: dict):
    assert is_valid_uuid(data.get("id", "")), "program id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["kind"] in ("LEAGUE", "CLINIC")
    assert data["status"] in ("OPEN", "FULL", "CLOSED")
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert isinstance(data["enrolled_count"], int) and data["enrolled_count"] >= 0
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_enrollment(data: dict):
    assert is_valid_uuid(data.get("id", "")), "enrollment id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["status"] in ("ENROLLED", "WITHDRAWN")
    assert isinstance(data["charged_cents"], int) and data["charged_cents"] >= 0
    assert isinstance(data["version"], int) and data["version"] >= 1
