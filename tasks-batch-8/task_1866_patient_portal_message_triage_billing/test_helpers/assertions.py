"""Entity assertions and domain invariant checkers.

Structural checks only: identity/timestamp shape, enum membership, and field
types. Behavioral claims live in the tests themselves.
"""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    BillingDisposition,
    ClaimCode,
    ClaimStatus,
    ConsentStatus,
    DeadlinePolicy,
    EntryKind,
    EscalationStatus,
    GrantStatus,
    MessageCategory,
    MessageStatus,
    MessageUrgency,
    NoticeKind,
    NoticeStatus,
    PlanType,
    PoolKind,
    StaffType,
)


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp into an aware datetime."""
    assert isinstance(value, str) and is_iso8601_timestamp(value), (
        f"Not an ISO 8601 UTC timestamp: {value!r}"
    )
    return datetime.fromisoformat(value.replace("Z", "+00:00")) \
        .astimezone(timezone.utc)


def assert_same_instant(actual: str, expected_iso: str, label: str = "timestamp"):
    """Two ISO 8601 strings denote the same instant (rendering may differ)."""
    actual_dt = parse_instant(actual)
    expected_dt = parse_instant(expected_iso)
    assert actual_dt == expected_dt, (
        f"{label}: expected instant {expected_iso}, got {actual}"
    )


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID with no type prefix"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601 UTC"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        "updated_at must be ISO 8601 UTC"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        "version must be a positive integer"


def _assert_optional_instant(data: dict, field: str):
    value = data.get(field)
    assert value is None or is_iso8601_timestamp(value), (
        f"{field} must be null or ISO 8601 UTC, got {value!r}"
    )


def assert_patient(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["plan_type"] in [p.value for p in PlanType]
    assert isinstance(data["outstanding_billed_cents"], int)
    assert isinstance(data["education_gate_open"], bool)


def assert_staff_member(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["staff_type"] in [s.value for s in StaffType]
    assert isinstance(data["open_inbox_count"], int)
    assert isinstance(data["inbox_overloaded"], bool)


def assert_pool(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["pool_kind"] in [k.value for k in PoolKind]
    assert data["deadline_policy"] in [d.value for d in DeadlinePolicy]
    for field in ("target_minutes_emergent", "target_minutes_urgent",
                  "target_minutes_routine"):
        assert isinstance(data[field], int), f"{field} must be an integer"


def assert_coverage_window(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("pool_id", "")), "pool_id must be a UUID"
    assert is_valid_uuid(data.get("staff_id", "")), "staff_id must be a UUID"
    assert is_iso8601_timestamp(data.get("start_utc", ""))
    assert is_iso8601_timestamp(data.get("end_utc", ""))


def assert_on_call_shift(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("provider_id", "")), "provider_id must be a UUID"
    assert is_iso8601_timestamp(data.get("start_utc", ""))
    assert is_iso8601_timestamp(data.get("end_utc", ""))


def assert_delegation_grant(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("delegator_provider_id", ""))
    assert is_valid_uuid(data.get("delegate_staff_id", ""))
    assert is_valid_uuid(data.get("pool_id", ""))
    assert is_iso8601_timestamp(data.get("start_utc", ""))
    assert is_iso8601_timestamp(data.get("end_utc", ""))
    assert data["status"] in [s.value for s in GrantStatus]
    _assert_optional_instant(data, "revoked_at")


def assert_portal_message(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("patient_id", "")), "patient_id must be a UUID"
    assert isinstance(data["subject"], str)
    assert isinstance(data["body"], str)
    assert is_iso8601_timestamp(data.get("received_at", ""))
    assert data["status"] in [s.value for s in MessageStatus]
    assert data.get("urgency") is None or data["urgency"] in \
        [u.value for u in MessageUrgency]
    assert data.get("category") is None or data["category"] in \
        [c.value for c in MessageCategory]
    assert data["billing_disposition"] in [b.value for b in BillingDisposition]
    assert isinstance(data["sla_breached"], bool)
    assert isinstance(data["clinical_minutes_total"], int)
    assert isinstance(data["reopen_count"], int)
    for field in ("triaged_at", "resolved_at", "first_response_at",
                  "response_due_at"):
        _assert_optional_instant(data, field)
    for field in ("assigned_pool_id", "assignee_id", "pending_cosign_by_id",
                  "resolved_by_id"):
        value = data.get(field)
        assert value is None or is_valid_uuid(value), (
            f"{field} must be null or a UUID, got {value!r}"
        )


def assert_staff_time_entry(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("message_id", ""))
    assert is_valid_uuid(data.get("staff_id", ""))
    assert data["entry_kind"] in [k.value for k in EntryKind]
    assert isinstance(data["minutes"], int)


def assert_consent_record(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("message_id", ""))
    assert is_valid_uuid(data.get("patient_id", ""))
    assert data["status"] in [s.value for s in ConsentStatus]
    assert data["disclosed_code"] in [c.value for c in ClaimCode]
    assert isinstance(data["disclosed_fee_cents"], int)
    assert is_iso8601_timestamp(data.get("requested_at", ""))
    _assert_optional_instant(data, "responded_at")


def assert_evisit_claim(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("message_id", ""))
    assert is_valid_uuid(data.get("patient_id", ""))
    assert is_valid_uuid(data.get("rendering_provider_id", ""))
    assert data["code"] in [c.value for c in ClaimCode]
    assert isinstance(data["fee_cents"], int)
    assert isinstance(data["patient_responsibility_cents"], int)
    assert data["status"] in [s.value for s in ClaimStatus]
    _assert_optional_instant(data, "submitted_at")
    _assert_optional_instant(data, "adjudicated_at")


def assert_escalation(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("message_id", ""))
    assert is_valid_uuid(data.get("provider_id", ""))
    assert isinstance(data["reason"], str)
    assert data["status"] in [s.value for s in EscalationStatus]
    _assert_optional_instant(data, "acknowledged_at")


def assert_education_notice(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("message_id", ""))
    assert is_valid_uuid(data.get("patient_id", ""))
    assert data["notice_kind"] in [k.value for k in NoticeKind]
    assert isinstance(data["blocking"], bool)
    assert isinstance(data["body"], str)
    assert data["status"] in [s.value for s in NoticeStatus]
    _assert_optional_instant(data, "acknowledged_at")


def assert_burden_summary(data: dict):
    assert isinstance(data["open_inbox_count"], int)
    assert isinstance(data["inbox_overloaded"], bool)
    assert isinstance(data["attributed_resolutions"], int)
    assert isinstance(data["touched_resolutions"], int)
    assert isinstance(data["clinical_minutes"], int)


def assert_staff_inbox(staff: dict, expected_count: int, expected_overloaded: bool):
    """Domain invariant: stored open_inbox_count drives inbox_overloaded."""
    assert staff["open_inbox_count"] == expected_count, (
        f"open_inbox_count: expected {expected_count}, "
        f"got {staff['open_inbox_count']}"
    )
    assert staff["inbox_overloaded"] is expected_overloaded, (
        f"inbox_overloaded: expected {expected_overloaded}, "
        f"got {staff['inbox_overloaded']}"
    )
