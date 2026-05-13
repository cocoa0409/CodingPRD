"""Per-entity assertions and domain invariant checkers.

PRD §2.4 splits entities into two field-shapes:

- Versioned (id + created_at + updated_at + version):
  Department, Handler, CategoryRule, WorkOrder, DepartmentAssignment,
  SatisfactionSurvey, SupervisionTask.

- Append-only / immutable-log (id + created_at only):
  ClarificationPause, AuditLog, SyncEvent.
"""
from __future__ import annotations
from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ---------------------------------------------------------------------------
# Shared shape checkers (PRD §2.4)
# ---------------------------------------------------------------------------
def _check_versioned_fields(data: Dict[str, Any], entity: str) -> None:
    """PRD §2.4: 'Every persisted resource carries a server-minted id
    that is a UUID string with no type prefix. Most resources
    additionally carry created_at, updated_at, and version, where the
    two timestamps are ISO 8601 UTC strings with three fractional digits
    and version is a non-negative integer that starts at 1 on creation
    and increments by 1 on every mutation.'"""
    assert "id" in data, f"{entity} missing id"
    assert is_valid_uuid(data["id"]), (
        f"{entity}.id must be UUID, got {data['id']!r}"
    )
    assert "created_at" in data and is_iso8601_timestamp(data["created_at"]), (
        f"{entity}.created_at must be ISO 8601 UTC"
    )
    assert "updated_at" in data and is_iso8601_timestamp(data["updated_at"]), (
        f"{entity}.updated_at must be ISO 8601 UTC"
    )
    assert "version" in data, f"{entity} missing version"
    assert isinstance(data["version"], int) and data["version"] >= 1, (
        f"{entity}.version must be >= 1, got {data.get('version')!r}"
    )


def _check_append_only_fields(data: Dict[str, Any], entity: str) -> None:
    """PRD §2.4: 'The exceptions are ClarificationPause, AuditLog, and
    SyncEvent: these three are append-only log-style records and
    therefore expose only id and created_at — both updated_at and
    version are absent.'"""
    assert "id" in data, f"{entity} missing id"
    assert is_valid_uuid(data["id"]), (
        f"{entity}.id must be UUID, got {data['id']!r}"
    )
    assert "created_at" in data and is_iso8601_timestamp(data["created_at"]), (
        f"{entity}.created_at must be ISO 8601 UTC"
    )


# ---------------------------------------------------------------------------
# Allowed enum sets (PRD §3.x)
# ---------------------------------------------------------------------------
DEPARTMENT_STATUS_SET = {"ACTIVE", "SUSPENDED"}
HANDLER_STATUS_SET = {"ACTIVE", "ON_LEAVE", "DISABLED"}

URGENCY_SET = {"LOW", "NORMAL", "HIGH", "CRITICAL"}
WORK_ORDER_STATUS_SET = {
    "REGISTERED", "CLASSIFIED", "DISPATCHED", "IN_PROGRESS",
    "RESOLVED", "FOLLOWED_UP", "CLOSED", "REOPENED", "REJECTED",
}
CLASSIFICATION_MODE_SET = {"PENDING", "RULE_BASED", "AI_ASSISTED"}
WARNING_STATE_SET = {"NONE", "YELLOW", "RED", "BREACHED"}

ASSIGNMENT_ROLE_SET = {"LEAD", "SUPPORTING"}
ASSIGNMENT_STAGE_STATUS_SET = {
    "DISPATCHED", "ACCEPTED", "REJECTED", "REASSIGNED",
    "OPINION_SUBMITTED", "ESCALATED",
}
OPINION_DECISION_SET = {"AGREE", "DISAGREE", "ABSTAIN"}

SURVEY_CHANNEL_SET = {"CALL", "SMS", "IM"}
SURVEY_STATUS_SET = {"DISPATCHED", "RESPONDED", "EXPIRED"}

SUPERVISION_REASON_SET = {
    "HIGH_PRIORITY_AUTO", "INACTIVITY_REMINDER",
    "DEADLINE_WARNING", "MANUAL",
}
SUPERVISION_STATUS_SET = {"OPEN", "ACKNOWLEDGED", "ESCALATED", "CLOSED"}

AUDIT_ACTION_SET = {
    "REGISTER", "CLASSIFY", "DISPATCH", "ACCEPT", "REJECT", "REASSIGN",
    "OPINION_SUBMIT", "ESCALATE", "PAUSE", "RESUME", "RESOLVE",
    "SURVEY_DISPATCH", "SURVEY_RESPOND", "REOPEN", "CLOSE",
    "SUPERVISION_CREATE", "SUPERVISION_ACK", "EVENT_SYNC",
}
SYNC_EVENT_TYPE_SET = {
    "DISPATCHED", "RESOLVED", "CLOSED", "REOPENED", "ESCALATED",
}
TARGET_PLATFORM_SET = {"IM", "GOVT_AFFAIRS", "INTER_DEPT"}
DELIVERY_STATUS_SET = {"PENDING", "DELIVERED", "FAILED"}


# ---------------------------------------------------------------------------
# Entity assertions
# ---------------------------------------------------------------------------
def assert_department(data: Dict[str, Any]) -> None:
    """PRD §3.1 + §2.4: Department has versioned shape and the listed
    fields (name, code, jurisdiction_codes, category_codes, status,
    pending_work_count)."""
    _check_versioned_fields(data, "Department")
    assert isinstance(data.get("name"), str) and len(data["name"]) >= 1
    assert isinstance(data.get("code"), str) and len(data["code"]) >= 2
    assert isinstance(data.get("jurisdiction_codes"), list)
    assert isinstance(data.get("category_codes"), list)
    assert data.get("status") in DEPARTMENT_STATUS_SET, (
        f"Department.status must be in {DEPARTMENT_STATUS_SET}"
    )
    assert isinstance(data.get("pending_work_count"), int)
    assert data["pending_work_count"] >= 0


def assert_handler(data: Dict[str, Any]) -> None:
    """PRD §3.1 + §2.4."""
    _check_versioned_fields(data, "Handler")
    assert isinstance(data.get("full_name"), str) and len(data["full_name"]) >= 1
    assert isinstance(data.get("department_id"), str)
    assert data.get("status") in HANDLER_STATUS_SET
    assert isinstance(data.get("open_assignment_count"), int)
    assert data["open_assignment_count"] >= 0


def assert_category_rule(data: Dict[str, Any]) -> None:
    """PRD §3.1 + §2.4."""
    _check_versioned_fields(data, "CategoryRule")
    assert isinstance(data.get("category_code"), str)
    assert isinstance(data.get("sub_category_code"), str)
    assert isinstance(data.get("lead_department_code"), str)
    assert isinstance(data.get("supporting_department_codes"), list)
    assert isinstance(data.get("statutory_time_limit_hours"), int)
    assert isinstance(data.get("committed_time_limit_hours"), int)
    assert (
        data["committed_time_limit_hours"]
        <= data["statutory_time_limit_hours"]
    ), "committed must be <= statutory"


def assert_work_order(data: Dict[str, Any]) -> None:
    """PRD §3.2, §3.3, §3.7, §3.8 + §2.4."""
    _check_versioned_fields(data, "WorkOrder")
    assert data.get("status") in WORK_ORDER_STATUS_SET
    assert data.get("urgency") in URGENCY_SET
    assert isinstance(data.get("anonymous"), bool)
    assert isinstance(data.get("jurisdiction_code"), str)
    assert isinstance(data.get("category_code"), str)
    assert isinstance(data.get("sub_category_code"), str)
    assert isinstance(data.get("content_text"), str)
    assert isinstance(data.get("difficulty_score"), int)
    assert 1 <= data["difficulty_score"] <= 10
    assert data.get("classification_mode") in CLASSIFICATION_MODE_SET
    assert isinstance(data.get("joint_handling"), bool)
    assert isinstance(data.get("supporting_department_ids"), list)
    assert isinstance(data.get("pause_accumulated_seconds"), int)
    assert data["pause_accumulated_seconds"] >= 0
    assert data.get("warning_state") in WARNING_STATE_SET
    assert isinstance(data.get("priority_flag"), bool)
    assert "registered_at" in data


def assert_department_assignment(data: Dict[str, Any]) -> None:
    """PRD §3.4, §3.5 + §2.4."""
    _check_versioned_fields(data, "DepartmentAssignment")
    assert isinstance(data.get("work_order_id"), str)
    assert isinstance(data.get("department_id"), str)
    assert data.get("role") in ASSIGNMENT_ROLE_SET
    assert data.get("stage_status") in ASSIGNMENT_STAGE_STATUS_SET


def assert_satisfaction_survey(data: Dict[str, Any]) -> None:
    """PRD §3.9 + §2.4."""
    _check_versioned_fields(data, "SatisfactionSurvey")
    assert isinstance(data.get("work_order_id"), str)
    assert data.get("channel") in SURVEY_CHANNEL_SET
    assert data.get("status") in SURVEY_STATUS_SET
    if data.get("score") is not None:
        assert isinstance(data["score"], int) and 1 <= data["score"] <= 5


def assert_supervision_task(data: Dict[str, Any]) -> None:
    """PRD §3.11 + §2.4."""
    _check_versioned_fields(data, "SupervisionTask")
    assert isinstance(data.get("work_order_id"), str)
    assert data.get("reason") in SUPERVISION_REASON_SET
    assert data.get("status") in SUPERVISION_STATUS_SET
    assert isinstance(data.get("escalation_level"), int)
    assert 0 <= data["escalation_level"] <= 3


def assert_clarification_pause(data: Dict[str, Any]) -> None:
    """PRD §3.6 + §2.4 (append-only)."""
    _check_append_only_fields(data, "ClarificationPause")
    assert isinstance(data.get("work_order_id"), str)
    assert isinstance(data.get("reason"), str)
    # paused_at present, resumed_at optional.
    assert "paused_at" in data


def assert_audit_log(data: Dict[str, Any]) -> None:
    """PRD §2.9 + §2.4 (append-only)."""
    _check_append_only_fields(data, "AuditLog")
    assert data.get("action") in AUDIT_ACTION_SET, (
        f"AuditLog.action must be one of {AUDIT_ACTION_SET}"
    )
    assert isinstance(data.get("actor_role"), str)
    assert isinstance(data.get("actor_id"), str)
    assert "occurred_at" in data


def assert_sync_event(data: Dict[str, Any]) -> None:
    """PRD §2.9 + §2.4 (append-only)."""
    _check_append_only_fields(data, "SyncEvent")
    assert data.get("event_type") in SYNC_EVENT_TYPE_SET
    assert data.get("target_platform") in TARGET_PLATFORM_SET
    assert data.get("delivery_status") in DELIVERY_STATUS_SET
    assert "emitted_at" in data


# ---------------------------------------------------------------------------
# Convenience finders
# ---------------------------------------------------------------------------
def find_first(items: Iterable[Dict[str, Any]],
               **filters: Any) -> Optional[Dict[str, Any]]:
    """Return the first item where every filter key matches."""
    for it in items:
        if all(it.get(k) == v for k, v in filters.items()):
            return it
    return None


def find_all(items: Iterable[Dict[str, Any]],
             **filters: Any) -> List[Dict[str, Any]]:
    """Return every item where every filter key matches."""
    return [it for it in items
            if all(it.get(k) == v for k, v in filters.items())]


# ---------------------------------------------------------------------------
# Domain invariant checkers
# ---------------------------------------------------------------------------
def assert_pause_invariant(work_order: Dict[str, Any],
                           clarification_pauses: List[Dict[str, Any]]) -> None:
    """PRD §3.13: 'the pause invariant requires that for every work order,
    the field pause_accumulated_seconds is exactly equal to the sum of
    duration_seconds across its ClarificationPause rows whose resumed_at
    is not null'."""
    resolved = [p for p in clarification_pauses
                if p.get("resumed_at") is not None
                and p.get("work_order_id") == work_order["id"]]
    total_duration = sum(int(p.get("duration_seconds", 0)) for p in resolved)
    assert work_order["pause_accumulated_seconds"] == total_duration, (
        f"pause_accumulated_seconds={work_order['pause_accumulated_seconds']}"
        f" must equal SUM(ClarificationPause.duration_seconds)={total_duration}"
    )


__all__ = [
    "DEPARTMENT_STATUS_SET", "HANDLER_STATUS_SET",
    "URGENCY_SET", "WORK_ORDER_STATUS_SET",
    "CLASSIFICATION_MODE_SET", "WARNING_STATE_SET",
    "ASSIGNMENT_ROLE_SET", "ASSIGNMENT_STAGE_STATUS_SET",
    "OPINION_DECISION_SET",
    "SURVEY_CHANNEL_SET", "SURVEY_STATUS_SET",
    "SUPERVISION_REASON_SET", "SUPERVISION_STATUS_SET",
    "AUDIT_ACTION_SET", "SYNC_EVENT_TYPE_SET",
    "TARGET_PLATFORM_SET", "DELIVERY_STATUS_SET",
    "assert_department", "assert_handler", "assert_category_rule",
    "assert_work_order", "assert_department_assignment",
    "assert_satisfaction_survey", "assert_supervision_task",
    "assert_clarification_pause", "assert_audit_log", "assert_sync_event",
    "find_first", "find_all", "assert_pause_invariant",
]
