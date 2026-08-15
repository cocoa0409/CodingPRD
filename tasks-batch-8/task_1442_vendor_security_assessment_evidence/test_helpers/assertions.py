"""Entity assertions and domain invariant checkers (PRD §2.4, §3).

Structural assertions use the framework's generic validators. Datetime
comparisons parse instants rather than comparing strings, so a serializer
that emits `.000Z` and one that omits fractional seconds both pass.
"""
from datetime import datetime

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


# --- instant helpers ---------------------------------------------------------

def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp into a comparable datetime."""
    assert isinstance(value, str), f"Expected ISO 8601 string, got {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def assert_instant_equal(actual: str, expected_iso: str) -> None:
    """Assert two instants coincide regardless of fractional-second formatting."""
    assert parse_instant(actual) == parse_instant(expected_iso), (
        f"Expected instant {expected_iso}, got {actual}"
    )


def assert_score(value, expected: float) -> None:
    """Assert a 2-dp score equals the expected value (PRD §2.10)."""
    assert value is not None, "Expected a computed score, got null"
    assert round(float(value), 2) == float(value), f"Score {value} exceeds 2 decimal places"
    assert abs(float(value) - expected) < 1e-9, f"Expected score {expected}, got {value}"


def _assert_common_fields(data: dict) -> None:
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


# --- per-entity assertions ---------------------------------------------------

def assert_vendor(data: dict) -> None:
    _assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert data["data_sensitivity"] in ("PUBLIC", "INTERNAL", "CONFIDENTIAL", "REGULATED")
    assert data["access_level"] in ("NONE", "READ_ONLY", "OPERATOR", "PRIVILEGED")
    assert data["criticality"] in ("LOW", "MEDIUM", "HIGH", "MISSION_CRITICAL")
    assert data["current_tier"] in ("TIER_1", "TIER_2", "TIER_3", "TIER_4")
    assert data["posture"] in (
        "ONBOARDING", "ASSESSING", "APPROVED", "CONDITIONAL",
        "SUSPENDED", "OFFBOARDING", "OFFBOARDED",
    )
    assert data.get("active_cycle_id") is None or isinstance(data["active_cycle_id"], str)
    assert isinstance(data["risk_score"], (int, float))
    assert 0.0 <= float(data["risk_score"]) <= 100.0, "risk_score must stay clamped to [0, 100]"


def assert_tier_policy(data: dict) -> None:
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["active"], bool)


def assert_template(data: dict) -> None:
    _assert_common_fields(data)
    assert isinstance(data["title"], str) and data["title"]
    assert data["status"] in ("DRAFT", "PUBLISHED", "RETIRED")
    assert isinstance(data["items"], list)
    assert isinstance(data["published_version"], int)


def assert_cycle(data: dict) -> None:
    _assert_common_fields(data)
    assert isinstance(data["vendor_id"], str)
    assert data["status"] in (
        "DRAFT", "ISSUED", "RESPONSE_RECEIVED", "SCORED", "EVIDENCE_REVIEW",
        "REMEDIATION", "RISK_ACCEPTANCE_REVIEW", "APPROVED", "REJECTED", "EXPIRED",
    )
    assert isinstance(data["open_exception_count"], int) and data["open_exception_count"] >= 0
    for field in ("questionnaire_score", "evidence_score", "composite_score"):
        assert data.get(field) is None or isinstance(data[field], (int, float)), field


def assert_response(data: dict) -> None:
    _assert_common_fields(data)
    assert isinstance(data["cycle_id"], str)
    assert data["status"] in ("DRAFT", "SUBMITTED", "RETURNED", "ACCEPTED")
    assert isinstance(data["revision_count"], int) and data["revision_count"] >= 0
    assert data.get("raw_score") is None or isinstance(data["raw_score"], (int, float))


def assert_evidence_artifact(data: dict) -> None:
    _assert_common_fields(data)
    assert isinstance(data["cycle_id"], str)
    assert data["kind"] in ("SOC2_TYPE1", "SOC2_TYPE2", "ISO27001", "PENTEST", "OTHER")
    assert data["status"] in (
        "RECEIVED", "UNDER_REVIEW", "REVIEWED_CLEAN", "REVIEWED_WITH_EXCEPTIONS", "REJECTED",
    )
    assert data.get("coverage_gap_days") is None or isinstance(data["coverage_gap_days"], int)


def assert_exception(data: dict) -> None:
    _assert_common_fields(data)
    assert isinstance(data["cycle_id"], str)
    assert data["source"] in ("QUESTIONNAIRE", "EVIDENCE", "MONITORING")
    assert data["severity"] in ("LOW", "MEDIUM", "HIGH", "CRITICAL")
    assert data["status"] in (
        "OPEN", "IN_REMEDIATION", "CLOSED_REMEDIATED", "CLOSED_ACCEPTED", "CLOSED_FALSE_POSITIVE",
    )


def assert_plan(data: dict) -> None:
    _assert_common_fields(data)
    assert isinstance(data["cycle_id"], str)
    assert data["status"] in ("PROPOSED", "ACCEPTED", "IN_PROGRESS", "COMPLETED", "VERIFIED", "REJECTED")
    assert isinstance(data["exception_ids"], list) and data["exception_ids"]
    assert isinstance(data["tasks"], list)


def assert_acceptance(data: dict) -> None:
    _assert_common_fields(data)
    assert isinstance(data["cycle_id"], str)
    assert data["status"] in ("REQUESTED", "APPROVED", "REJECTED", "EXPIRED")
    assert isinstance(data["exception_ids"], list) and data["exception_ids"]


def assert_addendum(data: dict) -> None:
    _assert_common_fields(data)
    assert isinstance(data["vendor_id"], str)
    assert data["status"] in ("REQUIRED", "DRAFTED", "SIGNED", "WAIVED")
    assert isinstance(data["clause_set"], list)


def assert_alert(data: dict) -> None:
    _assert_common_fields(data)
    assert isinstance(data["vendor_id"], str)
    assert data["signal"] in ("BREACH_REPORT", "CERT_LAPSE", "FINANCIAL_DISTRESS", "NEGATIVE_NEWS", "SCAN_FINDING")
    assert data["severity"] in ("LOW", "MEDIUM", "HIGH", "CRITICAL")
    assert data["status"] in ("OPEN", "ACKNOWLEDGED", "DISMISSED", "ESCALATED")


def assert_disclosure(data: dict) -> None:
    _assert_common_fields(data)
    assert isinstance(data["vendor_id"], str)
    assert data["status"] in ("DISCLOSED", "UNDER_REVIEW", "APPROVED", "REJECTED", "WITHDRAWN")


def assert_attestation(data: dict) -> None:
    _assert_common_fields(data)
    assert isinstance(data["vendor_id"], str)
    assert data["status"] in ("REQUESTED", "SUBMITTED", "VERIFIED", "REJECTED")


def assert_schedule_event(data: dict) -> None:
    """Append-only schedule event: id + created_at only (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "ReassessmentSchedule events must not carry version"
    assert "updated_at" not in data, "ReassessmentSchedule events must not carry updated_at"
    assert data["kind"] in ("TIER_CADENCE", "ALERT_ESCALATION", "ACCEPTANCE_EXPIRY", "OFFBOARDING_SLIP")


def assert_contact(data: dict) -> None:
    """Append-only contact record: id + created_at only (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "VendorContact records must not carry version"
    assert "updated_at" not in data, "VendorContact records must not carry updated_at"
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["is_primary"], bool)
