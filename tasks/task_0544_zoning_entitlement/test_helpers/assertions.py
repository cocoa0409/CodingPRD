"""Entity assertions and domain helpers for the Zoning Entitlement API."""
from datetime import datetime, timezone
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _parse_instant(value: str) -> datetime:
    """Parse an ISO-8601 UTC timestamp, tolerating a trailing Z and optional
    fractional seconds, into a timezone-aware datetime."""
    assert isinstance(value, str) and value, f"expected an ISO timestamp, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def instant_equals(actual: str, expected: str) -> bool:
    """True when two ISO timestamps denote the same instant, regardless of whether
    fractional-second precision is present (PRD §2.4 timestamps carry 3 fractional
    digits; whole-day date fields may be serialized either way)."""
    return _parse_instant(actual) == _parse_instant(expected)


def assert_instant_equals(actual: str, expected: str, label: str = "timestamp"):
    assert instant_equals(actual, expected), \
        f"Expected {label} == {expected}, got {actual}"


def assert_common_fields(data: dict):
    """id / created_at / updated_at / version for full-lifecycle entities (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_append_only_fields(data: dict):
    """id / created_at only for append-only records (CompletenessReview, Finding)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_parcel(data: dict):
    assert_common_fields(data)
    assert isinstance(data["apn"], str) and data["apn"]
    assert data["zoning_district"] in ["RES", "COMM", "IND", "AG"]
    assert data["status"] in ["AVAILABLE", "UNDER_APPLICATION", "ENTITLED", "SUBDIVIDED"]
    assert isinstance(data["assessed_fee_cents"], int) and data["assessed_fee_cents"] >= 0


def assert_application(data: dict):
    assert_common_fields(data)
    assert data["application_type"] in ["VARIANCE", "REZONE", "CUP", "SUBDIVISION"]
    assert is_valid_uuid(data.get("parcel_id", "")), "parcel_id must be a UUID"
    assert is_valid_uuid(data.get("applicant_id", "")), "applicant_id must be a UUID"
    assert data["status"] in [
        "DRAFT", "SUBMITTED", "INCOMPLETE", "ACCEPTED", "SCHEDULED",
        "DECIDED_APPROVED", "DECIDED_DENIED", "EFFECTIVE", "EXPIRED",
        "RECORDED", "WITHDRAWN", "DENIED_ON_APPEAL", "CLOSED",
    ]
    assert isinstance(data["revision_count"], int) and data["revision_count"] >= 0


def assert_hearing(data: dict):
    assert_common_fields(data)
    assert data["body"] in ["PLANNING_COMMISSION", "CITY_COUNCIL"]
    assert data["status"] in ["SCHEDULED", "CANCELLED"]
    assert isinstance(data["agenda_capacity"], int) and data["agenda_capacity"] >= 1
    assert isinstance(data["agenda_slots_remaining"], int)


def assert_agenda_item(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("hearing_id", "")), "hearing_id must be a UUID"
    assert is_valid_uuid(data.get("application_id", "")), "application_id must be a UUID"
    assert data["status"] in ["PLACED", "APPROVED", "DENIED", "CONTINUED", "REMOVED"]


def assert_notice(data: dict):
    assert_common_fields(data)
    assert data["notice_kind"] in ["MAILED", "PUBLISHED", "POSTED"]
    assert isinstance(data["recipient_count"], int) and data["recipient_count"] >= 0
    assert isinstance(data["used_expanded_radius"], bool)
    assert data["status"] in ["SENT", "VOIDED"]


def assert_appeal(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("application_id", "")), "application_id must be a UUID"
    assert data["status"] in ["FILED", "UPHELD", "DENIED", "WITHDRAWN"]


def assert_plat(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("application_id", "")), "application_id must be a UUID"
    assert data["status"] in ["PENDING", "RECORDED", "VACATED", "REJECTED"]


def assert_impact_fee(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("plat_id", "")), "plat_id must be a UUID"
    assert data["status"] in ["PROVISIONAL", "ASSESSED", "PAID", "VOIDED"]
    assert isinstance(data["total_fee_cents"], int)
    assert isinstance(data["gross_fee_cents"], int)


def assert_completeness_review(data: dict):
    assert_append_only_fields(data)
    assert data["determination"] in ["COMPLETE", "INCOMPLETE"]
    assert isinstance(data["cycle_number"], int) and data["cycle_number"] >= 1
    # Append-only record: must NOT expose updated_at / version.
    assert "updated_at" not in data, "CompletenessReview is append-only (no updated_at)"
    assert "version" not in data, "CompletenessReview is append-only (no version)"


def assert_finding(data: dict):
    assert_append_only_fields(data)
    assert isinstance(data["supports_approval"], bool)
    assert "updated_at" not in data, "Finding is append-only (no updated_at)"
    assert "version" not in data, "Finding is append-only (no version)"
