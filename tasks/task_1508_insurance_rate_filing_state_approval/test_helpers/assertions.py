"""Entity assertions and domain invariant checkers (PRD §2.5, §2.6, §3)."""
from datetime import datetime, timezone

import pytest
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _parse_instant(value: str) -> datetime:
    """Parse an ISO-8601 UTC timestamp, tolerating optional fractional digits."""
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def assert_instant_equals(actual: str, expected: str):
    """Two renderings of the same instant compare equal (PRD §2.6 allows the
    three-fractional-digit form, so '...T00:00:00Z' and '...T00:00:00.000Z'
    denote the same instant)."""
    assert is_iso8601_timestamp(actual), f"not an ISO-8601 UTC timestamp: {actual!r}"
    assert _parse_instant(actual) == _parse_instant(expected), (
        f"expected instant {expected}, got {actual}"
    )


def assert_pct(actual, expected: float):
    """Computed percentages are stored at exactly 4 decimal places (PRD §2.6);
    the tolerance only absorbs binary float noise, never a rounding difference."""
    assert actual == pytest.approx(expected, abs=1e-9), (
        f"expected {expected}, got {actual}"
    )


def assert_common_fields(data: dict):
    """PRD §2.5: every resource carries id/created_at/updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        "updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        "version must be an integer starting at 1"
    )


def assert_product(data: dict):
    assert_common_fields(data)
    assert isinstance(data["product_code"], str) and data["product_code"]
    assert isinstance(data["name"], str) and data["name"]
    assert data.get("current_locked_indication_id") is None or isinstance(
        data["current_locked_indication_id"], str
    )


def assert_profile(data: dict):
    assert_common_fields(data)
    assert data["filing_method"] in ("PRIOR_APPROVAL", "FILE_AND_USE", "USE_AND_FILE")
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2


def assert_indication(data: dict):
    assert_common_fields(data)
    assert data["status"] in (
        "DRAFT",
        "IN_ACTUARIAL_REVIEW",
        "APPROVED",
        "LOCKED",
        "SUPERSEDED",
    )
    assert data["variant"] in ("INCURRED_CREDIBILITY", "PAID_PURE")
    assert isinstance(data["review_round"], int) and data["review_round"] >= 1


def assert_filing(data: dict):
    assert_common_fields(data)
    assert data["status"] in (
        "DRAFT",
        "READY",
        "SUBMITTED",
        "UNDER_OBJECTION",
        "APPROVED",
        "DEEMED_APPROVED",
        "EFFECTIVE",
        "SUPERSEDED",
        "DISAPPROVED",
        "WITHDRAWN",
    )
    assert isinstance(data["open_objection_count"], int)
    assert data["open_objection_count"] >= 0


def assert_component(data: dict):
    assert_common_fields(data)
    assert data["component_type"] in ("RATE", "RULE", "FORM")
    assert data["status"] in ("DRAFT", "FINAL", "SUPERSEDED", "WITHDRAWN")


def assert_deviation(data: dict):
    assert_common_fields(data)
    assert data["deviation_type"] in ("RATE_FACTOR", "RULE_TEXT", "FORM_TEXT")
    assert data["status"] in (
        "PROPOSED",
        "APPROVED",
        "REJECTED",
        "WITHDRAWN",
        "SUPERSEDED",
    )


def assert_objection(data: dict):
    assert_common_fields(data)
    assert data["status"] in (
        "RAISED",
        "RESPONSE_DRAFTED",
        "RESPONSE_SUBMITTED",
        "OVERDUE",
        "RESOLVED",
        "REOPENED",
        "WITHDRAWN",
    )
    assert isinstance(data["reopen_count"], int) and data["reopen_count"] >= 0
    assert isinstance(data["late_breach"], bool)


def assert_response(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("DRAFT", "SUBMITTED", "SUPERSEDED")


def assert_wave(data: dict):
    assert_common_fields(data)
    assert data["status"] in (
        "SCHEDULED",
        "RELEASED",
        "REVERSED",
        "CANCELLED",
        "COMPLETED",
    )
    assert isinstance(data["rated_policy_count"], int)
    assert isinstance(data["excluded_late_notice_count"], int)


def assert_policy(data: dict):
    assert_common_fields(data)
    assert data["status"] in (
        "PENDING",
        "RATED",
        "NOTICE_SENT",
        "COMPLETED",
        "RESCINDED",
    )
    assert isinstance(data["current_premium_cents"], int)


def assert_calendar_entry(data: dict):
    assert_common_fields(data)
    assert data["entry_type"] in (
        "OBJECTION_RESPONSE_DUE",
        "DEEMER_DATE",
        "WAVE_WINDOW",
        "RENEWAL_NOTICE_DUE",
        "EFFECTIVE_DATE",
    )
    assert data["status"] in ("PENDING", "MET", "MISSED", "WAIVED")
    assert is_iso8601_timestamp(data["due_date"])
