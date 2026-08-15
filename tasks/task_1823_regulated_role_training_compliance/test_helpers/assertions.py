"""Entity assertions and domain invariant checkers.

Timestamps recorded by the system are readings of the logical clock; tests
compare them as instants (ISO 8601 with optional fractional seconds), never
as raw strings, so serialization format choices stay free.
"""
from datetime import datetime, timezone

import pytest
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp (with or without fractional digits)."""
    assert isinstance(value, str), f"expected timestamp string, got {value!r}"
    assert is_iso8601_timestamp(value), f"not an ISO 8601 UTC timestamp: {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def assert_instant_equal(actual: str, expected_iso: str, label: str = "timestamp"):
    """Assert two ISO 8601 timestamps denote the same instant."""
    assert parse_instant(actual) == parse_instant(expected_iso), (
        f"{label}: expected instant {expected_iso}, got {actual}"
    )


def assert_pct_equal(actual, expected: float, label: str = "percentage"):
    """Assert a 2-decimal rate/percentage equals the expected value."""
    assert float(actual) == pytest.approx(expected, abs=1e-9), (
        f"{label}: expected {expected}, got {actual}"
    )


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        "version must be a positive integer"
    )


def assert_regulator(data: dict):
    _assert_common(data)
    assert isinstance(data["code"], str) and data["code"]
    assert data["deadline_mode"] in ("CALENDAR", "BUSINESS_DAYS")
    assert isinstance(data["recordkeeping_years"], int)
    assert 1 <= data["recordkeeping_years"] <= 25
    assert isinstance(data["escalation_interval_days"], int)
    assert 1 <= data["escalation_interval_days"] <= 90
    assert isinstance(data["reminder_days_before_due"], int)
    assert 0 <= data["reminder_days_before_due"] <= 30
    assert data["status"] in ("ACTIVE", "RETIRED")


def assert_role(data: dict):
    _assert_common(data)
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["name"], str) and data["name"]
    assert data["status"] in ("ACTIVE", "RETIRED")


def assert_curriculum(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("regulator_id", ""))
    assert isinstance(data["code"], str) and data["code"]
    assert 0 <= float(data["passing_score_pct"]) <= 100
    assert isinstance(data["validity_months"], int) and 1 <= data["validity_months"] <= 120
    assert isinstance(data["max_attempts"], int) and 1 <= data["max_attempts"] <= 10
    assert data["evidence_requirement"] in ("NONE", "CERTIFICATE", "PROCTORED_CERTIFICATE")
    assert "recordkeeping_years_override" in data
    assert isinstance(data["effective_recordkeeping_years"], int)
    assert 1 <= data["effective_recordkeeping_years"] <= 25
    assert data["status"] in ("DRAFT", "ACTIVE", "RETIRED")


def assert_curriculum_version(data: dict):
    _assert_common(data)
    assert isinstance(data["version_no"], int) and data["version_no"] >= 1
    assert is_iso8601_timestamp(data.get("effective_from", ""))
    assert data.get("effective_to") is None or is_iso8601_timestamp(data["effective_to"])
    assert isinstance(data["content_uri"], str)


def assert_role_requirement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("role_id", ""))
    assert is_valid_uuid(data.get("curriculum_id", ""))
    assert data["recurrence"] in ("INITIAL_ONLY", "VALIDITY_CYCLE")
    assert isinstance(data["due_in_days"], int) and 1 <= data["due_in_days"] <= 365
    assert data["criticality"] in ("HARD", "SOFT")
    assert data["status"] in ("ACTIVE", "RETIRED")


def assert_employee(data: dict):
    _assert_common(data)
    assert isinstance(data["employee_no"], str) and data["employee_no"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert is_iso8601_timestamp(data.get("hired_at", ""))
    assert data.get("manager_id") is None or is_valid_uuid(data["manager_id"])
    assert is_valid_uuid(data.get("current_role_id", ""))
    assert data["status"] in ("ACTIVE", "ON_LEAVE", "TERMINATED")
    assert isinstance(data["compliance_blocked"], bool)
    assert isinstance(data["verified_completed_count"], int)
    assert data["verified_completed_count"] >= 0


def assert_role_change(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("employee_id", ""))
    assert isinstance(data["from_role_code"], str)
    assert is_valid_uuid(data.get("to_role_id", ""))
    assert is_iso8601_timestamp(data.get("effective_at", ""))
    assert data["status"] in ("SCHEDULED", "APPLIED", "CANCELLED", "REVERSED")


def assert_assignment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("employee_id", ""))
    assert is_valid_uuid(data.get("role_requirement_id", ""))
    assert is_valid_uuid(data.get("curriculum_id", ""))
    assert data["trigger_source"] in (
        "NEW_HIRE", "ROLE_CHANGE", "REQUIREMENT_SWEEP", "RECURRENCE", "MANUAL", "REVERSAL",
    )
    assert is_iso8601_timestamp(data.get("assigned_at", ""))
    assert is_iso8601_timestamp(data.get("base_due_at", ""))
    assert is_iso8601_timestamp(data.get("due_at", ""))
    assert isinstance(data["active_extension_days"], int) and data["active_extension_days"] >= 0
    assert isinstance(data["attempts_used"], int) and data["attempts_used"] >= 0
    assert data["progress_status"] in (
        "ASSIGNED", "IN_PROGRESS", "SUBMITTED", "VERIFIED_COMPLETED",
        "FAILED", "CANCELLED", "EXPIRED",
    )
    assert data["deadline_status"] in (
        "ON_TRACK", "DUE_SOON", "OVERDUE", "ESCALATED", "FROZEN",
    )


def assert_due_at_invariant(data: dict):
    """due_at == base_due_at + active_extension_days days, at all times."""
    from datetime import timedelta

    base = parse_instant(data["base_due_at"])
    due = parse_instant(data["due_at"])
    assert due == base + timedelta(days=data["active_extension_days"]), (
        f"due_at invariant violated: {data['due_at']} != {data['base_due_at']} "
        f"+ {data['active_extension_days']}d"
    )


def assert_completion(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("assignment_id", ""))
    assert isinstance(data["attempt_no"], int) and data["attempt_no"] >= 1
    assert 0 <= float(data["score_pct"]) <= 100
    assert data["evidence_type"] in ("NONE", "CERTIFICATE", "PROCTORED_CERTIFICATE")
    assert is_iso8601_timestamp(data.get("submitted_at", ""))
    assert isinstance(data["is_late"], bool)
    assert isinstance(data["passed"], bool)
    assert data["review_status"] in ("PENDING_REVIEW", "ACCEPTED", "REJECTED", "VOIDED")


def assert_campaign(data: dict):
    _assert_common(data)
    assert isinstance(data["year"], int) and 2000 <= data["year"] <= 2100
    assert is_valid_uuid(data.get("regulator_id", ""))
    assert is_iso8601_timestamp(data.get("window_open_at", ""))
    assert is_iso8601_timestamp(data.get("window_close_at", ""))
    assert isinstance(data["statement_version"], str)
    assert data["status"] in ("DRAFT", "OPEN", "CLOSED", "FINALIZED")
    assert "metrics" in data


def assert_attestation(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("campaign_id", ""))
    assert is_valid_uuid(data.get("employee_id", ""))
    assert data["status"] in (
        "PENDING", "ATTESTED", "EXCEPTION_PENDING", "EXEMPTED", "EXPIRED", "BLOCKED",
    )


def assert_exception(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("attestation_id", ""))
    assert data["reason_code"] in ("MEDICAL_LEAVE", "MILITARY_DUTY", "ROLE_TRANSITION", "OTHER")
    assert isinstance(data["detail"], str) and len(data["detail"]) >= 10
    assert data["status"] in ("REQUESTED", "APPROVED", "DENIED")


def assert_notice(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("assignment_id", ""))
    assert data["level"] in (1, 2, 3)
    assert data["kind"] in ("DUE_SOON_REMINDER", "OVERDUE_MANAGER", "ESCALATION_COMPLIANCE")
    assert data.get("recipient_employee_id") is None or is_valid_uuid(data["recipient_employee_id"])
    assert is_iso8601_timestamp(data.get("triggered_at", ""))
    assert data["status"] in ("OPEN", "ACKNOWLEDGED")


def assert_leave(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("employee_id", ""))
    assert is_iso8601_timestamp(data.get("start_date", ""))
    assert is_iso8601_timestamp(data.get("end_date", ""))
    assert parse_instant(data["end_date"]) >= parse_instant(data["start_date"])


def assert_audit_report(data: dict):
    _assert_common(data)
    assert isinstance(data["population_spec"], dict)
    assert is_valid_uuid(data["population_spec"].get("regulator_id", ""))
    assert data["metric_variant"] in ("STRICT", "AUDIT_LENIENT")
    assert is_iso8601_timestamp(data.get("generated_at", ""))
    assert is_iso8601_timestamp(data.get("recordkeeping_expires_at", ""))
    metrics = data["metrics"]
    assert isinstance(metrics["population_size"], int)
    assert isinstance(metrics["compliant_count"], int)
    assert isinstance(metrics["overdue_count"], int)
    assert_pct_equal(metrics["compliance_rate_pct"], float(metrics["compliance_rate_pct"]))
    assert 0 <= float(metrics["compliance_rate_pct"]) <= 100
