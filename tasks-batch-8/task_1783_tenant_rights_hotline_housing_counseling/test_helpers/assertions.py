"""Entity assertions and domain invariant checkers (PRD §2.2, §2.4, §3).

Every assertion uses PRD-exact field names. Timestamp comparisons parse both
sides to instants so that an implementation's ISO 8601 formatting freedom
(PRD §2.4 pins three fractional digits on created_at/updated_at) never turns
into a false failure.
"""
from datetime import datetime

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


# ---------------------------------------------------------------------------
# Instant helpers
# ---------------------------------------------------------------------------
def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 timestamp (with Z or offset) into a datetime."""
    assert isinstance(value, str) and value, f"expected ISO timestamp string, got {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def assert_instant_equal(actual: str, expected_iso: str, label: str = "instant"):
    """Assert two ISO 8601 timestamps denote the same instant."""
    assert parse_instant(actual) == parse_instant(expected_iso), (
        f"Expected {label} == {expected_iso}, got {actual}"
    )


# ---------------------------------------------------------------------------
# Common-field helpers
# ---------------------------------------------------------------------------
def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        "version must be an integer starting at 1"
    )


def _assert_optional_instant(data: dict, field: str):
    value = data.get(field)
    if value is not None:
        assert is_iso8601_timestamp(value), f"{field} must be ISO 8601 when present"


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------
def assert_jurisdiction(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["code"], str) and data["code"]
    assert data["level"] in ("STATE", "COUNTY", "CITY")
    assert isinstance(data["eviction_notice_days"], int)
    assert isinstance(data["habitability_repair_days"], int)
    assert isinstance(data["deposit_cap_months"], (int, float))
    assert isinstance(data["deposit_interest_required"], bool)


def assert_rights_script(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("DRAFT", "IN_REVIEW", "PUBLISHED", "SUPERSEDED", "RETIRED")
    assert isinstance(data["version_no"], int) and data["version_no"] >= 1
    assert data["issue_category"] in ("EVICTION", "HABITABILITY", "DEPOSIT")
    assert isinstance(data.get("author_counselor_id"), str)
    _assert_optional_instant(data, "effective_from")
    _assert_optional_instant(data, "effective_until")


def assert_self_help_resource(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("CURRENT", "OUTDATED", "RETIRED")
    assert isinstance(data.get("linked_script_id"), str)
    assert isinstance(data.get("language_code"), str)


def assert_counselor(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("ACTIVE", "SUSPENDED", "INACTIVE")
    assert isinstance(data.get("languages"), list)
    assert isinstance(data.get("certified_jurisdiction_codes"), list)
    assert isinstance(data.get("certified_categories"), list)
    assert isinstance(data.get("trained_script_ids"), list)
    assert isinstance(data.get("is_script_reviewer"), bool)
    _assert_optional_instant(data, "certification_expires_at")


def assert_interpreter(data: dict):
    _assert_common_fields(data)
    assert isinstance(data.get("language_code"), str) and data["language_code"]


def assert_caller(data: dict):
    _assert_common_fields(data)
    assert isinstance(data.get("alias"), str)
    assert data["channel"] in ("PHONE", "CHAT", "TTY", "VIDEO")
    assert isinstance(data.get("is_anonymous"), bool)
    assert isinstance(data.get("pii_purged"), bool)
    assert isinstance(data.get("do_not_aggregate"), bool)
    assert isinstance(data.get("accessibility_needs"), list)
    if data.get("is_anonymous"):
        assert data.get("phone") is None, "anonymous callers must have null phone"


def assert_consent_record(data: dict):
    _assert_common_fields(data)
    assert data["consent_type"] in ("RECORDING", "FOLLOW_UP", "LEGAL_AID_RELEASE", "DATA_SHARING")
    assert data["status"] in ("GRANTED", "REVOKED", "EXPIRED")
    _assert_optional_instant(data, "granted_at")
    _assert_optional_instant(data, "expires_at")
    _assert_optional_instant(data, "revoked_at")


def assert_call_session(data: dict):
    _assert_common_fields(data)
    assert data["session_status"] in (
        "QUEUED", "ASSIGNED", "ACTIVE", "WRAPPED_UP", "DROPPED", "ABANDONED"
    )
    assert data["interpretation_status"] in (
        "NOT_REQUIRED", "REQUESTED", "CONNECTED", "FAILED"
    )
    assert isinstance(data.get("queue_wait_seconds"), int)
    assert isinstance(data.get("failed_interpreter_ids"), list)
    _assert_optional_instant(data, "actual_start_at")
    _assert_optional_instant(data, "actual_end_at")


def assert_case(data: dict):
    _assert_common_fields(data)
    assert data["status"] in (
        "OPEN", "IN_PROGRESS", "PENDING_FOLLOW_UP", "ESCALATED", "RESOLVED", "CLOSED"
    )
    assert data["score_variant"] in ("PROVISIONAL", "VERIFIED")
    assert data["urgency_tier"] in ("STANDARD", "ELEVATED", "CRITICAL")
    assert isinstance(data.get("priority_score"), int)
    assert 0 <= data["priority_score"] <= 100, "priority_score is clamped to 0..100"
    assert isinstance(data.get("missed_follow_up_count"), int)
    assert isinstance(data.get("required_follow_up_count"), int)
    assert isinstance(data.get("escalation_level"), int)
    assert isinstance(data.get("legal_hold"), bool)
    exposure = data.get("deposit_exposure_cents")
    if exposure is not None:
        assert isinstance(exposure, int) and exposure >= 0
    _assert_optional_instant(data, "last_escalated_at")
    _assert_optional_instant(data, "closed_at")


def assert_case_note(data: dict):
    """CaseNote is the append-only exception of PRD §2.4: id + created_at only."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only notes carry no updated_at"
    assert "version" not in data, "append-only notes carry no version"
    assert isinstance(data.get("case_id"), str)
    assert isinstance(data.get("body"), str)
    assert isinstance(data.get("is_confidential"), bool)
    assert isinstance(data.get("system_generated"), bool)


def assert_follow_up(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("SCHEDULED", "DUE", "COMPLETED", "MISSED", "CANCELLED")
    assert isinstance(data.get("auto_created"), bool)
    assert isinstance(data.get("required_count_at_schedule"), int)
    _assert_optional_instant(data, "scheduled_for")
    _assert_optional_instant(data, "completed_at")


def assert_legal_aid_org(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("ACTIVE", "PAUSED")
    assert isinstance(data.get("weekly_capacity"), int)
    assert isinstance(data.get("current_week_reserved"), int)
    assert data["current_week_reserved"] >= 0


def assert_referral(data: dict):
    _assert_common_fields(data)
    assert data["referral_type"] in ("LEGAL_AID", "SELF_HELP")
    assert data["status"] in (
        "PROPOSED", "DISPATCHED", "ACCEPTED", "DECLINED", "EXPIRED", "CANCELLED"
    )
    assert isinstance(data.get("declined_org_ids"), list)
    if data.get("cancel_reason") is not None:
        assert data["cancel_reason"] in (
            "OPERATOR", "CONSENT_REVOKED", "CONSENT_EXPIRED", "SCRIPT_OUTDATED"
        )
    _assert_optional_instant(data, "sla_dispatch_by")
    _assert_optional_instant(data, "accept_by")
    _assert_optional_instant(data, "dispatched_at")


def assert_retention_policy(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("ACTIVE", "INACTIVE")
    assert isinstance(data.get("retention_days"), int)


def assert_purge_job(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("PENDING", "EXECUTED", "BLOCKED_BY_HOLD")
    assert isinstance(data.get("created_by_sweep"), bool)
    _assert_optional_instant(data, "executed_at")


# ---------------------------------------------------------------------------
# Domain invariants
# ---------------------------------------------------------------------------
def assert_case_score_invariants(data: dict):
    """Score/tier/cadence consistency that must hold on any case read (PRD §3.6)."""
    score = data["priority_score"]
    expected_tier = (
        "CRITICAL" if score >= 70 else "ELEVATED" if score >= 40 else "STANDARD"
    )
    assert data["urgency_tier"] == expected_tier, (
        f"tier {data['urgency_tier']} inconsistent with score {score}"
    )
    expected_required = {"STANDARD": 1, "ELEVATED": 2, "CRITICAL": 3}[expected_tier]
    assert data["required_follow_up_count"] == expected_required, (
        f"required_follow_up_count {data['required_follow_up_count']} "
        f"inconsistent with tier {expected_tier}"
    )


def assert_escalation_rate(value, expected: float):
    """Analytics rate: a JSON number rounded half-up to four decimals (PRD §3.9)."""
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"escalation_rate must be a number, got {value!r}"
    )
    assert abs(float(value) - expected) < 1e-9, (
        f"expected escalation_rate {expected}, got {value}"
    )
