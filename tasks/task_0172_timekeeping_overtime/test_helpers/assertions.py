"""Entity assertions and domain invariant checkers.

Each `assert_{entity}` verifies the PRD-declared field set, types, and
enumerated values on a response body. Mutable resources (Employee,
Shift, TimeEdit, TipDeclaration, Workweek) carry id + created_at +
updated_at + version (PRD §2.4). Append-only resources (Punch,
MealBreak, DetentionEvent, AuditEntry) carry only id + created_at.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ===========================================================================
# Enum-like sets — PRD §3
# ===========================================================================
JURISDICTIONS = {"CA", "FED"}
CLASSIFICATIONS = {"EXEMPT", "NON_EXEMPT"}
EMPLOYEE_STATUSES = {"ACTIVE", "TERMINATED"}
SHIFT_STATES = {"SCHEDULED", "OPEN", "CLOSED", "DISPUTED", "FINALIZED",
                "VOIDED"}
PUNCH_TYPES = {"IN", "OUT", "MEAL_OUT", "MEAL_IN"}
PUNCH_SOURCES = {"TIMECLOCK", "EDIT"}
TIME_EDIT_STATES = {"PENDING", "APPROVED", "REJECTED", "REVERTED"}
TIME_EDIT_REASON_CODES = {"CLERICAL", "MISSED_PUNCH", "EQUIPMENT_FAILURE",
                          "FRAUD_CORRECTION"}
DETENTION_TIERS = {"NONE", "TIER_1", "TIER_2", "TIER_3"}
WORKWEEK_PAYROLL_STATUSES = {"OPEN", "POSTED", "LOCKED"}
AUDIT_ACTIONS = {"TIME_EDIT_SUBMITTED", "TIME_EDIT_APPROVED",
                 "TIME_EDIT_REJECTED", "TIME_EDIT_REVERTED",
                 "SHIFT_FINALIZED", "WORKWEEK_LOCKED"}
AUDIT_SUBJECT_ENTITIES = {"Shift", "TimeEdit", "Workweek"}
ACTOR_ROLES = {"Employee", "Supervisor", "PayrollAdmin"}


# ===========================================================================
# Common-field assertions — PRD §2.4
# ===========================================================================
def assert_common_fields(data: Dict[str, Any]) -> None:
    """Assert id, created_at, updated_at, version for mutable resources.

    PRD §2.4: "Resources ... are mutable and carry four common
    properties on every read: `id` is a server-minted UUID string with
    no domain prefix; `created_at` and `updated_at` are ISO 8601 UTC
    timestamps with three fractional digits ... and `version` is an
    integer that begins at 1 on creation and increments by exactly 1
    on every mutation."
    """
    assert is_valid_uuid(data.get("id", "")), (
        f"id must be a valid UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    version = data.get("version")
    assert isinstance(version, int) and version >= 1, (
        f"version must be an integer >= 1, got {version!r}"
    )


def assert_append_only_fields(data: Dict[str, Any]) -> None:
    """Assert id + created_at and absence of updated_at / version.

    PRD §2.4: "Resources of type `Punch`, `MealBreak`, `DetentionEvent`,
    and `AuditEntry` are append-only event records — they carry only
    `id` and `created_at`; neither `updated_at` nor `version` is present
    on them".
    """
    assert is_valid_uuid(data.get("id", "")), (
        f"id must be a valid UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert "updated_at" not in data, (
        "PRD §2.4: append-only resource must not carry updated_at"
    )
    assert "version" not in data, (
        "PRD §2.4: append-only resource must not carry version"
    )


def assert_version_incremented_by(new_version: int, old_version: int,
                                   delta: int = 1) -> None:
    """PRD §2.4: version increments by exactly 1 on every mutation."""
    expected = old_version + delta
    assert new_version == expected, (
        f"PRD §2.4: version must increment by {delta} "
        f"(was {old_version}, expected {expected}, got {new_version})"
    )


# ===========================================================================
# Employee — PRD §3.1
# ===========================================================================
def assert_employee(data: Dict[str, Any]) -> None:
    """PRD §3.1 / §2.4 — validate Employee response."""
    assert_common_fields(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["jurisdiction"] in JURISDICTIONS, (
        f"jurisdiction must be in {JURISDICTIONS}, "
        f"got {data['jurisdiction']!r}"
    )
    assert data["classification"] in CLASSIFICATIONS, (
        f"classification must be in {CLASSIFICATIONS}, "
        f"got {data['classification']!r}"
    )
    assert data["status"] in EMPLOYEE_STATUSES, (
        f"status must be in {EMPLOYEE_STATUSES}, got {data['status']!r}"
    )
    # tipped_role default false (PRD §3.1).
    tipped = data.get("tipped_role")
    if tipped is not None:
        assert isinstance(tipped, bool), "tipped_role must be boolean"
    # base_hourly_rate_cents required for NON_EXEMPT.
    if data["classification"] == "NON_EXEMPT":
        rate = data.get("base_hourly_rate_cents")
        assert isinstance(rate, int) and rate >= 725, (
            "PRD §3.1: NON_EXEMPT must carry base_hourly_rate_cents >= 725"
        )


# ===========================================================================
# Shift — PRD §3.2
# ===========================================================================
def assert_shift(data: Dict[str, Any]) -> None:
    """PRD §3.2 / §2.4 — validate Shift response."""
    assert_common_fields(data)
    assert is_valid_uuid(data.get("employee_id", "")), (
        f"employee_id must be UUID, got {data.get('employee_id')!r}"
    )
    assert is_iso8601_timestamp(data["scheduled_start"]), (
        "scheduled_start must be ISO 8601"
    )
    assert is_iso8601_timestamp(data["scheduled_end"]), (
        "scheduled_end must be ISO 8601"
    )
    assert data["state"] in SHIFT_STATES, (
        f"state must be in {SHIFT_STATES}, got {data['state']!r}"
    )
    actual_start = data.get("actual_start")
    if actual_start is not None:
        assert is_iso8601_timestamp(actual_start), (
            "actual_start must be ISO 8601"
        )
    actual_end = data.get("actual_end")
    if actual_end is not None:
        assert is_iso8601_timestamp(actual_end), (
            "actual_end must be ISO 8601"
        )
    if "detention_minutes" in data:
        assert isinstance(data["detention_minutes"], int)
        assert data["detention_minutes"] >= 0
    if "meal_break_premium_owed_cents" in data:
        assert isinstance(data["meal_break_premium_owed_cents"], int)
        assert data["meal_break_premium_owed_cents"] >= 0


def assert_shift_state(data: Dict[str, Any], expected: str) -> None:
    """Assert the shift is in the expected state with a clear message."""
    assert data["state"] == expected, (
        f"expected Shift.state == {expected!r}, got {data['state']!r}"
    )


# ===========================================================================
# Punch — PRD §3.2 (append-only)
# ===========================================================================
def assert_punch(data: Dict[str, Any]) -> None:
    """PRD §3.2 / §2.4 — validate Punch response (append-only)."""
    assert_append_only_fields(data)
    assert data["punch_type"] in PUNCH_TYPES, (
        f"punch_type must be in {PUNCH_TYPES}, got {data['punch_type']!r}"
    )
    assert is_iso8601_timestamp(data["punched_at"]), (
        "punched_at must be ISO 8601"
    )
    assert data["source"] in PUNCH_SOURCES, (
        f"source must be in {PUNCH_SOURCES}, got {data['source']!r}"
    )
    superseded = data.get("superseded_by_edit_id")
    if superseded is not None:
        assert is_valid_uuid(superseded)


# ===========================================================================
# TimeEdit — PRD §3.5
# ===========================================================================
def assert_time_edit(data: Dict[str, Any]) -> None:
    """PRD §3.5 / §2.4 — validate TimeEdit response."""
    assert_common_fields(data)
    assert is_valid_uuid(data["shift_id"]), "shift_id must be UUID"
    assert is_valid_uuid(data["target_punch_id"]), (
        "target_punch_id must be UUID"
    )
    assert is_iso8601_timestamp(data["proposed_punched_at"]), (
        "proposed_punched_at must be ISO 8601"
    )
    assert data["reason_code"] in TIME_EDIT_REASON_CODES, (
        f"reason_code must be in {TIME_EDIT_REASON_CODES}, "
        f"got {data['reason_code']!r}"
    )
    assert data["state"] in TIME_EDIT_STATES, (
        f"state must be in {TIME_EDIT_STATES}, got {data['state']!r}"
    )
    assert isinstance(data["idempotency_key"], str)
    assert 1 <= len(data["idempotency_key"]) <= 64


# ===========================================================================
# TipDeclaration — PRD §3.7
# ===========================================================================
def assert_tip_declaration(data: Dict[str, Any]) -> None:
    """PRD §3.7 / §2.4 — validate TipDeclaration response."""
    assert_common_fields(data)
    assert is_valid_uuid(data["shift_id"]), "shift_id must be UUID"
    assert isinstance(data["declared_tips_cents"], int)
    assert data["declared_tips_cents"] >= 0


# ===========================================================================
# Workweek — PRD §3.6
# ===========================================================================
def assert_workweek(data: Dict[str, Any]) -> None:
    """PRD §3.6 / §2.4 — validate Workweek response."""
    assert_common_fields(data)
    assert is_valid_uuid(data["employee_id"]), "employee_id must be UUID"
    assert is_iso8601_timestamp(data["week_start"]), (
        "week_start must be ISO 8601"
    )
    assert data["payroll_status"] in WORKWEEK_PAYROLL_STATUSES, (
        f"payroll_status must be in {WORKWEEK_PAYROLL_STATUSES}, "
        f"got {data['payroll_status']!r}"
    )
    for hours_field in (
        "total_hours", "regular_hours", "overtime_hours", "double_time_hours",
    ):
        assert isinstance(data[hours_field], (int, float)), (
            f"{hours_field} must be numeric"
        )
        assert data[hours_field] >= 0, (
            f"{hours_field} must be >= 0"
        )
    assert isinstance(data["gross_pay_cents"], int)
    assert data["gross_pay_cents"] >= 0


# ===========================================================================
# DetentionEvent — PRD §3.4 (append-only)
# ===========================================================================
def assert_detention_event(data: Dict[str, Any]) -> None:
    """PRD §3.4 / §2.4 — validate DetentionEvent response."""
    assert_append_only_fields(data)
    assert is_valid_uuid(data["shift_id"]), "shift_id must be UUID"
    assert isinstance(data["minutes_past_scheduled_end"], int)
    assert data["minutes_past_scheduled_end"] >= 0
    assert isinstance(data["premium_owed_cents"], int)
    assert data["premium_owed_cents"] >= 0
    assert data["tier"] in DETENTION_TIERS, (
        f"tier must be in {DETENTION_TIERS}, got {data['tier']!r}"
    )


# ===========================================================================
# MealBreak — PRD §3.3 (append-only)
# ===========================================================================
def assert_meal_break(data: Dict[str, Any]) -> None:
    """PRD §3.3 / §2.4 — validate MealBreak response."""
    assert_append_only_fields(data)
    assert is_valid_uuid(data["shift_id"]), "shift_id must be UUID"
    assert isinstance(data["duration_minutes"], int)
    assert data["duration_minutes"] >= 0
    assert isinstance(data["taken_before_fifth_hour"], bool)


# ===========================================================================
# AuditEntry — PRD §3.8 (append-only)
# ===========================================================================
def assert_audit_entry(data: Dict[str, Any]) -> None:
    """PRD §3.8 / §2.4 — validate AuditEntry response."""
    assert_append_only_fields(data)
    assert isinstance(data["actor_user_id"], str)
    assert data["actor_role"] in ACTOR_ROLES, (
        f"actor_role must be in {ACTOR_ROLES}, got {data['actor_role']!r}"
    )
    assert data["action"] in AUDIT_ACTIONS, (
        f"action must be in {AUDIT_ACTIONS}, got {data['action']!r}"
    )
    assert data["subject_entity"] in AUDIT_SUBJECT_ENTITIES, (
        f"subject_entity must be in {AUDIT_SUBJECT_ENTITIES}, "
        f"got {data['subject_entity']!r}"
    )
    assert isinstance(data["subject_id"], str) and len(data["subject_id"]) > 0


# ===========================================================================
# Audit search helpers
# ===========================================================================
def find_audit_entries(entries: Iterable[Dict[str, Any]],
                       *,
                       action: Optional[str] = None,
                       subject_entity: Optional[str] = None,
                       subject_id: Optional[str] = None,
                       ) -> List[Dict[str, Any]]:
    """Filter an iterable of audit entries by action / subject."""
    result: List[Dict[str, Any]] = []
    for entry in entries:
        if action is not None and entry.get("action") != action:
            continue
        if (subject_entity is not None
                and entry.get("subject_entity") != subject_entity):
            continue
        if subject_id is not None and entry.get("subject_id") != subject_id:
            continue
        result.append(entry)
    return result


def assert_audit_action_present(entries: Iterable[Dict[str, Any]],
                                action: str,
                                *,
                                subject_id: Optional[str] = None) -> None:
    """Assert at least one audit entry matches the action / subject."""
    matches = find_audit_entries(
        entries, action=action, subject_id=subject_id,
    )
    assert matches, (
        f"expected audit entry with action={action!r}"
        f" subject_id={subject_id!r}, found none "
        f"in {[e.get('action') for e in entries]}"
    )


def assert_audit_action_absent(entries: Iterable[Dict[str, Any]],
                               action: str) -> None:
    """Assert no audit entry carries the given action."""
    matches = find_audit_entries(entries, action=action)
    assert not matches, (
        f"expected no audit entry with action={action!r}, found {matches}"
    )


# ===========================================================================
# Money / cents precision
# ===========================================================================
def assert_cents_integer(value: Any, *, field: str = "value") -> None:
    """PRD §2.6: monetary fields are integer whole cents."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{field} must be an integer (whole cents per PRD §2.6), "
        f"got {value!r} of type {type(value).__name__}"
    )


__all__ = [
    # Enum sets
    "JURISDICTIONS",
    "CLASSIFICATIONS",
    "EMPLOYEE_STATUSES",
    "SHIFT_STATES",
    "PUNCH_TYPES",
    "PUNCH_SOURCES",
    "TIME_EDIT_STATES",
    "TIME_EDIT_REASON_CODES",
    "DETENTION_TIERS",
    "WORKWEEK_PAYROLL_STATUSES",
    "AUDIT_ACTIONS",
    "AUDIT_SUBJECT_ENTITIES",
    "ACTOR_ROLES",
    # Common
    "assert_common_fields",
    "assert_append_only_fields",
    "assert_version_incremented_by",
    # Entities
    "assert_employee",
    "assert_shift",
    "assert_shift_state",
    "assert_punch",
    "assert_time_edit",
    "assert_tip_declaration",
    "assert_workweek",
    "assert_detention_event",
    "assert_meal_break",
    "assert_audit_entry",
    # Audit utilities
    "find_audit_entries",
    "assert_audit_action_present",
    "assert_audit_action_absent",
    # Money
    "assert_cents_integer",
]
