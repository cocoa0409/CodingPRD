"""Entity assertions and domain invariant checkers (PRD §2.5 common fields)."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _parse_instant(value):
    """Parse an ISO 8601 timestamp string to an aware datetime (Z-tolerant)."""
    assert isinstance(value, str), f"expected timestamp string, got {value!r}"
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def assert_same_instant(actual, expected_iso, label="timestamp"):
    """Assert two timestamps denote the same instant.

    PRD pins the *instant* of event stamps ("stamped with the clock",
    "thirty days after issue") but not their string serialization format,
    so comparisons are made on parsed instants rather than raw strings.
    """
    assert is_iso8601_timestamp(actual), f"{label} not ISO 8601: {actual!r}"
    assert _parse_instant(actual) == _parse_instant(expected_iso), (
        f"{label}: {actual!r} != instant {expected_iso!r}"
    )


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data["version"], int) and data["version"] >= 1, "version must be >= 1"


def assert_landlord(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["fee_balance_cents"], int)


def assert_jurisdiction_rule(data: dict):
    _assert_common(data)
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert data["criminal_lookback_years"] >= 0
    assert data["eviction_lookback_years"] >= 0


def assert_criteria(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "PUBLISHED", "ARCHIVED")
    assert isinstance(data["min_credit_score"], int)


def assert_applicant(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]


def assert_application(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "SCREENING", "SCORED",
        "APPROVED", "DENIED", "WITHDRAWN", "CANCELLED",
    )
    assert data["identity_status"] in ("UNVERIFIED", "VERIFIED", "FAILED")
    assert isinstance(data["identity_attempts"], int)
    assert isinstance(data["fee_charged_cents"], int)


def assert_report(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "DRAFT", "DELIVERED", "UNDER_DISPUTE", "AMENDED", "RE_DELIVERED", "VOIDED",
    )
    assert isinstance(data["included_record_count"], int)


def assert_record(data: dict):
    _assert_common(data)
    assert data["record_type"] in ("EVICTION", "CRIMINAL")
    assert data["status"] in ("INCLUDED", "SUPPRESSED", "DISPUTED", "REMOVED")


def assert_income_verification(data: dict):
    _assert_common(data)
    assert data["status"] in ("PENDING", "VERIFIED", "FAILED")


def assert_guarantor(data: dict):
    _assert_common(data)
    assert data["status"] in ("PENDING", "APPROVED", "DECLINED")


def assert_notice(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "ISSUED", "RESCINDED")
    assert isinstance(data["reason_codes"], list)


def assert_dispute(data: dict):
    _assert_common(data)
    assert data["status"] in ("FILED", "UNDER_REINVESTIGATION", "RESOLVED_UPHELD", "RESOLVED_CORRECTED")


def assert_audit_run(data: dict):
    """ConsistencyAuditRun is an immutable event record: id + created_at only,
    with no updated_at and no version (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "audit run must not carry version"
    assert "updated_at" not in data, "audit run must not carry updated_at"
    assert isinstance(data["applications_examined"], int)
    assert isinstance(data["inconsistencies_found"], int)
    assert isinstance(data["inconsistent_application_ids"], list)
