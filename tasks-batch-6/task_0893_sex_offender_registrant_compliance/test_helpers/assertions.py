"""Entity assertions, timestamp helpers, and domain invariant checkers."""
from datetime import datetime
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def parse_ts(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp regardless of fractional-second formatting
    (accepts a trailing Z or an explicit offset, with or without .000)."""
    assert value is not None, "timestamp is None"
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


def assert_same_instant(actual: str, expected: str):
    """Assert two ISO 8601 timestamps denote the same instant, ignoring the
    fractional-second rendering (.000Z vs Z)."""
    assert parse_ts(actual) == parse_ts(expected), (
        f"Expected instant {expected}, got {actual}"
    )


def assert_registrant(data: dict):
    assert is_valid_uuid(data.get("id", "")), "registrant id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data.get("full_name"), str) and data["full_name"]
    assert data["status"] in [
        "PENDING", "ACTIVE", "DELINQUENT", "ABSCONDER", "DEREGISTERED",
    ], f"unexpected registrant status {data.get('status')}"
    assert "version" in data and isinstance(data["version"], int)


def assert_jurisdiction(data: dict):
    assert is_valid_uuid(data.get("id", "")), "jurisdiction id must be valid UUID"
    assert data["status"] in ["ACTIVE", "INACTIVE"]
    assert isinstance(data["active_registrant_count"], int)
    assert isinstance(data["active_travel_hold_count"], int)


def assert_offense(data: dict):
    assert is_valid_uuid(data.get("id", "")), "offense id must be valid UUID"
    assert data["offense_class"] in ["CLASS_A", "CLASS_B", "CLASS_C"]
    assert isinstance(data["offense_points"], int)
    # Offense is an append-only audit record: no version / updated_at exposed.
    assert "version" not in data, "Offense must not expose version"
    assert "updated_at" not in data, "Offense must not expose updated_at"


def assert_address(data: dict):
    assert is_valid_uuid(data.get("id", "")), "address id must be valid UUID"
    assert data["address_type"] in ["RESIDENCE", "EMPLOYMENT", "SCHOOL", "TEMPORARY"]
    assert data["status"] in ["VERIFIED", "HISTORICAL"]


def assert_flag(data: dict):
    assert is_valid_uuid(data.get("id", "")), "flag id must be valid UUID"
    assert data["flag_type"] in [
        "LATE_VERIFICATION", "UNREPORTED_MOVE", "EXCLUSION_VIOLATION",
        "TRAVEL_VIOLATION", "ABSCONDED",
    ]
    assert data["severity"] in ["MINOR", "MAJOR", "CRITICAL"]
    assert isinstance(data["base_points"], int)
    assert data["status"] in ["OPEN", "RESOLVED"]


def assert_travel_notice(data: dict):
    assert is_valid_uuid(data.get("id", "")), "travel notice id must be valid UUID"
    assert data["status"] in [
        "SUBMITTED", "APPROVED", "DENIED", "ACTIVE", "COMPLETED", "OVERDUE", "CANCELLED",
    ]


def assert_petition(data: dict):
    assert is_valid_uuid(data.get("id", "")), "petition id must be valid UUID"
    assert data["petition_type"] in ["DEREGISTER", "TIER_REDUCTION"]
    assert data["decision"] in ["PENDING", "GRANTED", "DENIED", "WITHDRAWN"]
    assert isinstance(data["adjudicated_risk_score"], int)
    assert isinstance(data["eligibility_met"], bool)


def assert_notification(data: dict):
    assert is_valid_uuid(data.get("id", "")), "notification id must be valid UUID"
    assert isinstance(data["radius_meters"], int)
    assert isinstance(data["estimated_recipients"], int)
    assert isinstance(data["actual_recipients"], int)
    # NotificationRecord is append-only: no version / updated_at.
    assert "version" not in data, "NotificationRecord must not expose version"
    assert "updated_at" not in data, "NotificationRecord must not expose updated_at"


def assert_verification_event(data: dict):
    assert is_valid_uuid(data.get("id", "")), "verification id must be valid UUID"
    assert data["result"] == "VERIFIED"
    assert "version" not in data, "VerificationEvent must not expose version"
    assert "updated_at" not in data, "VerificationEvent must not expose updated_at"
