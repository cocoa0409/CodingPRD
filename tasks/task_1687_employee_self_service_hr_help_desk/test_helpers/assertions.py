"""Entity assertions and domain invariant checkers (PRD §2.2, §2.4, §3)."""
from datetime import datetime, timezone

import pytest

from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
    assert_timestamp_format,
)


# ---------------------------------------------------------------------------
# Instant comparison
# The PRD pins the *value* of timestamps (an instant on the logical clock) and
# the ISO 8601 UTC format, so comparisons parse both sides and compare the
# instants rather than relying on one particular rendering of zero fractions.
# ---------------------------------------------------------------------------

def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp string into an aware datetime."""
    assert isinstance(value, str), f"timestamp must be a string, got {type(value)}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def assert_instant_equals(actual: str, expected_iso: str) -> None:
    """Assert two ISO 8601 timestamps denote the same instant."""
    assert_timestamp_format(actual)
    actual_dt = parse_instant(actual)
    expected_dt = parse_instant(expected_iso)
    assert actual_dt == expected_dt, f"Expected instant {expected_iso}, got {actual}"


# ---------------------------------------------------------------------------
# Common-field helpers (PRD §2.4)
# ---------------------------------------------------------------------------

def _assert_primary_fields(data: dict) -> None:
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601 UTC"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601 UTC"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_append_only_fields(data: dict) -> None:
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601 UTC"
    assert "updated_at" not in data, "append-only records must not expose updated_at"
    assert "version" not in data, "append-only records must not expose version"


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------

def assert_employee(data: dict) -> None:
    _assert_primary_fields(data)
    assert isinstance(data["employee_number"], str) and data["employee_number"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert data["status"] in ("ACTIVE", "ON_LEAVE", "TERMINATED")
    assert isinstance(data["has_pending_dcr"], bool)
    assert isinstance(data["open_ticket_count"], int) and data["open_ticket_count"] >= 0


def assert_team(data: dict) -> None:
    _assert_primary_fields(data)
    assert isinstance(data["name"], str) and data["name"]


def assert_agent(data: dict) -> None:
    _assert_primary_fields(data)
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert data["tier"] in ("T1", "T2")
    assert data["clearance"] in ("STANDARD", "SENSITIVE")
    assert is_valid_uuid(data.get("team_id", "")), "team_id must be a UUID"
    assert isinstance(data["capacity_max"], int) and data["capacity_max"] >= 0
    assert isinstance(data["active"], bool)


def assert_agent_with_computed(data: dict) -> None:
    """Single-agent reads expose the computed load and health fields (PRD §3.1)."""
    assert_agent(data)
    assert isinstance(data["assigned_open_count"], int) and data["assigned_open_count"] >= 0
    assert data.get("rolling_csat") is None or isinstance(data["rolling_csat"], (int, float))
    assert isinstance(data["coaching_hold"], bool)


def assert_category(data: dict) -> None:
    _assert_primary_fields(data)
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["is_sensitive"], bool)
    assert is_valid_uuid(data.get("specialist_team_id", "")), "specialist_team_id must be a UUID"
    assert isinstance(data["active"], bool)


def assert_sla_policy(data: dict) -> None:
    _assert_primary_fields(data)
    assert data["priority"] in ("P1", "P2", "P3", "P4")
    assert isinstance(data["first_response_minutes"], int) and data["first_response_minutes"] > 0
    assert isinstance(data["resolution_minutes"], int) and data["resolution_minutes"] > 0
    assert data["clock_mode"] in ("WALL_CLOCK", "BUSINESS_HOURS")


def assert_kb_article(data: dict) -> None:
    _assert_primary_fields(data)
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["body"], str)
    assert data["status"] in ("DRAFT", "IN_REVIEW", "PUBLISHED", "SUPERSEDED", "ARCHIVED")
    assert isinstance(data["author_user_id"], str) and data["author_user_id"]


def assert_article_view(data: dict) -> None:
    _assert_append_only_fields(data)
    assert is_valid_uuid(data.get("employee_id", "")), "employee_id must be a UUID"
    assert is_valid_uuid(data.get("article_id", "")), "article_id must be a UUID"
    assert data["deflection_outcome"] in ("NONE", "TICKET_CREATED")


def assert_ticket(data: dict) -> None:
    _assert_primary_fields(data)
    assert is_valid_uuid(data.get("employee_id", "")), "employee_id must be a UUID"
    assert is_valid_uuid(data.get("category_id", "")), "category_id must be a UUID"
    assert data["priority"] in ("P1", "P2", "P3", "P4")
    assert isinstance(data["sensitive"], bool)
    assert data["tier"] in ("T1", "T2")
    assert data["workflow_status"] in (
        "NEW", "TRIAGED", "IN_PROGRESS", "PENDING_EMPLOYEE", "ESCALATED",
        "RESOLVED", "REOPENED", "CLOSED", "CANCELLED",
    )
    assert data["sla_status"] in (
        "ON_TRACK", "AT_RISK", "BREACHED_RESPONSE", "BREACHED_RESOLUTION", "MET",
    )
    assert isinstance(data["escalation_count"], int) and data["escalation_count"] >= 0
    assert isinstance(data["reopen_count"], int) and data["reopen_count"] >= 0


def assert_ticket_event(data: dict) -> None:
    _assert_append_only_fields(data)
    assert is_valid_uuid(data.get("ticket_id", "")), "ticket_id must be a UUID"
    assert data["event_type"] in (
        "CREATED", "TRIAGED", "ASSIGNED", "UNASSIGNED", "RESPONDED",
        "INFO_REQUESTED", "INFO_PROVIDED", "ESCALATED", "RESOLVED", "REOPENED",
        "CLOSED", "CANCELLED", "AUTO_CLOSED", "SLA_BREACH", "COACHING_RELEASE",
    )
    assert isinstance(data["actor_user_id"], str) and data["actor_user_id"]


def assert_event_type_sequence(events: list, expected_types: list) -> None:
    """Assert the event log's event_type sequence matches exactly, in order."""
    actual = [e["event_type"] for e in events]
    assert actual == list(expected_types), f"Expected event sequence {expected_types}, got {actual}"


def assert_data_change_request(data: dict) -> None:
    _assert_primary_fields(data)
    assert is_valid_uuid(data.get("employee_id", "")), "employee_id must be a UUID"
    assert data["change_type"] in ("ADDRESS", "DIRECT_DEPOSIT")
    assert isinstance(data["new_values"], dict)
    assert data["approval_status"] in (
        "PENDING_VERIFICATION", "PENDING_APPROVAL", "APPLIED", "REJECTED", "CANCELLED",
    )
    assert data["fraud_status"] in ("NOT_REQUIRED", "PENDING", "VERIFIED", "FAILED", "LOCKED")


def assert_fraud_verification(data: dict) -> None:
    _assert_primary_fields(data)
    assert is_valid_uuid(data.get("dcr_id", "")), "dcr_id must be a UUID"
    assert data["method"] in ("SECURITY_CODE", "MANAGER_CONFIRMATION")
    assert isinstance(data["attempts"], int) and data["attempts"] >= 0
    assert data["status"] in ("PENDING", "VERIFIED", "FAILED", "LOCKED")


def assert_survey(data: dict) -> None:
    _assert_primary_fields(data)
    assert is_valid_uuid(data.get("ticket_id", "")), "ticket_id must be a UUID"
    assert is_valid_uuid(data.get("employee_id", "")), "employee_id must be a UUID"
    assert data["status"] in ("ISSUED", "SUBMITTED", "EXPIRED")


def assert_staffing_window(data: dict) -> None:
    _assert_primary_fields(data)
    assert is_valid_uuid(data.get("team_id", "")), "team_id must be a UUID"
    assert data["status"] in ("PLANNED", "ACTIVE", "COMPLETED", "CANCELLED")


def assert_agent_shift(data: dict) -> None:
    _assert_primary_fields(data)
    assert is_valid_uuid(data.get("agent_id", "")), "agent_id must be a UUID"
    assert is_valid_uuid(data.get("staffing_window_id", "")), "staffing_window_id must be a UUID"
    assert data["status"] in ("SCHEDULED", "CANCELLED")


def assert_audit_log_entry(data: dict) -> None:
    _assert_append_only_fields(data)
    assert is_valid_uuid(data.get("employee_id", "")), "employee_id must be a UUID"
    assert is_valid_uuid(data.get("dcr_id", "")), "dcr_id must be a UUID"
    assert isinstance(data["field_changed"], str) and data["field_changed"]
    assert data["change_source"] == "DCR_APPLIED"


# ---------------------------------------------------------------------------
# Domain invariants
# ---------------------------------------------------------------------------

def assert_open_ticket_conservation(agent_a: dict, agent_b: dict, expected_total: int) -> None:
    """SUM(assigned_open_count) over the agents equals the open assigned tickets."""
    total = agent_a["assigned_open_count"] + agent_b["assigned_open_count"]
    assert total == expected_total, (
        f"assigned_open_count conservation violated: "
        f"{agent_a['assigned_open_count']} + {agent_b['assigned_open_count']} != {expected_total}"
    )


def assert_csat(value, expected: float) -> None:
    """Compare a reported CSAT mean (2dp round-half-up) against the expected figure."""
    assert value == pytest.approx(expected, abs=1e-6), f"Expected {expected}, got {value}"
