"""Entity assertions and domain invariant checkers.

Uses the framework's generic validators (is_valid_uuid, is_iso8601_timestamp,
assert_cost_precision) internally. Field names are PRD-exact (§2.4, §3).
"""
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp, assert_cost_precision,
)


def _assert_common(data: dict):
    """Common fields every entity carries (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version begins at 1 (PRD §2.4)"


def assert_center(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["posture"] in ("OPEN", "QUALITY_HOLD", "LOCKED"), \
        f"posture must be OPEN|QUALITY_HOLD|LOCKED, got {data.get('posture')!r}"
    assert isinstance(data["critical_ack_sla_minutes"], int)
    assert isinstance(data["repeat_rate_threshold_pct"], (int, float))
    assert isinstance(data["admin_locked"], bool)
    assert isinstance(data["total_acquired_series"], int)
    assert isinstance(data["total_repeat_reject_series"], int)
    assert isinstance(data["repeat_reject_rate_pct"], (int, float))
    assert is_iso8601_timestamp(data["now_utc"]), "now_utc must be ISO 8601"


def assert_modality(data: dict):
    _assert_common(data)
    assert data["modality_type"] in ("MRI", "CT", "XRAY", "US")
    assert isinstance(data["base_rvu"], (int, float)) and data["base_rvu"] >= 0
    assert isinstance(data["requires_contrast_screening"], bool)
    assert isinstance(data["requires_prior_auth"], bool)


def assert_room(data: dict):
    _assert_common(data)
    assert data["status"] in ("AVAILABLE", "OUT_OF_SERVICE")
    assert isinstance(data["cleanup_buffer_minutes"], int)


def assert_staff(data: dict):
    _assert_common(data)
    assert data["staff_role"] in ("TECHNOLOGIST", "RADIOLOGIST", "NURSE")
    assert isinstance(data["credentialed_modalities"], list)
    assert len(data["credentialed_modalities"]) >= 1, "credentialed_modalities is non-empty (PRD §3.1)"
    assert isinstance(data["signed_rvu_total"], (int, float))


def assert_order(data: dict):
    _assert_common(data)
    assert data["priority"] in ("STAT", "ROUTINE")
    assert isinstance(data["requires_contrast"], bool)
    assert data["status"] in (
        "REQUESTED", "BENEFIT_CHECKED", "SCREEN_CLEARED", "SCHEDULED",
        "READ_PENDING", "SIGNED_OFF", "ADDENDUM_REQUESTED", "CANCELLED",
    )


def assert_prior_auth(data: dict):
    _assert_common(data)
    assert data["status"] in ("PENDING", "AUTHORIZED", "DENIED")
    assert isinstance(data["requested_units"], int)
    assert isinstance(data["authorized_units"], int)
    assert isinstance(data["benefit_copay_cents"], int)


def assert_screening(data: dict):
    _assert_common(data)
    assert data["outcome"] in ("PENDING", "CLEARED", "BLOCKED")
    assert isinstance(data["egfr_value"], (int, float))
    assert isinstance(data["has_contrast_allergy"], bool)
    assert isinstance(data["is_pregnant"], bool)
    assert isinstance(data["metal_implant_unsafe"], bool)


def assert_exam(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "BOOKED", "CHECKED_IN", "ACQUIRING", "ACQUIRED",
        "READING", "READ_COMPLETE", "SIGNED_OFF", "CANCELLED",
    )
    assert is_iso8601_timestamp(data["scheduled_start_utc"])
    assert is_iso8601_timestamp(data["scheduled_end_utc"])


def assert_series(data: dict):
    _assert_common(data)
    assert data["outcome"] in ("CAPTURING", "ACCEPTED", "REPEATED", "REJECTED")
    assert isinstance(data["series_label"], str)


def assert_report(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "FINAL", "AMENDED")
    assert isinstance(data["has_critical_finding"], bool)
    assert isinstance(data["rvu_credited"], (int, float))
    assert isinstance(data["addendum_count"], int)


def assert_critical_result(data: dict):
    _assert_common(data)
    assert data["status"] in ("UNACKNOWLEDGED", "ACKNOWLEDGED")
    assert data["notified_party_role"] in ("ORDERING_PROVIDER", "COVERING_PROVIDER", "RAPID_RESPONSE")
    assert isinstance(data["sla_breached"], bool)
    assert is_iso8601_timestamp(data["raised_at_utc"])


# ─── Domain invariant checkers ────────────────────────────────────────

def assert_rate_precision(rate: float):
    """repeat_reject_rate_pct and other computed numerics are rounded to 2
    decimal places (PRD §2.7)."""
    assert_cost_precision(rate)
