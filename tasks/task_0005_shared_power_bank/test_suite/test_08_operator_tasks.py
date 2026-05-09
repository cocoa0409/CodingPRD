"""
Operator-task workflow (PRD §3.8): auto-assign, completion, REPAIR_DISPATCH
gating on linked RepairTicket.status, and admin cancel branch.
"""

from __future__ import annotations

import pytest

from test_helpers import (
    ADMIN_HEADERS,
    FAULTY_SLOT_WEIGHT,
    LOW_BATTERY_WEIGHT,
    OFFLINE_BONUS,
    OPERATOR_2_HEADERS,
    OPERATOR_HEADERS,
    advance_clock_to,
    api_client,
    assert_operator_task,
    heartbeat,
    trigger_anomaly_cascade,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# auto-assign happy path (PRD §3.8)
# ---------------------------------------------------------------------------


def test_auto_assign_returns_pending_task_and_sets_assigned(api):
    """PRD §3.8: "The winning task has its assigned_operator_id written to
    the caller's X-User-ID and its status advanced from PENDING to ASSIGNED."
    """
    env = trigger_anomaly_cascade()
    res = api.auto_assign_task({"city_code": "BJ"}, OPERATOR_HEADERS)
    task = validate_success(res, 200)
    assert_operator_task(task)
    assert task["status"] == "ASSIGNED"
    assert task["assigned_operator_id"] is not None


def test_auto_assign_no_pending_returns_no_pending_tasks(api):
    """PRD §3.8: "When the eligible set is empty the call is rejected with
    ERR_NO_PENDING_TASKS."
    """
    res = api.auto_assign_task({"city_code": "BJ"}, OPERATOR_HEADERS)
    validate_error(res, "ERR_NO_PENDING_TASKS")


# ---------------------------------------------------------------------------
# Priority score (PRD §3.8)
# ---------------------------------------------------------------------------


def test_priority_score_includes_faulty_slot_weight(api):
    """PRD §3.8: "The priority score for a cabinet is computed as the
    cabinet's low_battery_count multiplied by 10, plus the cabinet's
    faulty_slot_count multiplied by 5, plus a 50-point offline bonus when
    the cabinet's online_status is OFFLINE."

    Anomaly cascade leaves: 1 FAULTY slot, 0 AVAILABLE devices below 30 (the
    only device is now FAULTY), cabinet ONLINE → priority = 0+5+0=5.
    """
    env = trigger_anomaly_cascade()
    res = api.auto_assign_task({"city_code": "BJ"}, OPERATOR_HEADERS)
    task = validate_success(res, 200)
    assert task["priority_score"] == 5


# ---------------------------------------------------------------------------
# Complete REPAIR_DISPATCH gated by ticket status (PRD §2.7 priority 19 / §3.8)
# ---------------------------------------------------------------------------


def test_complete_repair_dispatch_blocked_by_unresolved_ticket(api):
    """PRD §2.7 priority 19: "when completing an operator task whose task_type
    is REPAIR_DISPATCH, the linked RepairTicket has reached RESOLVED
    (rejection: ERR_TICKET_UNRESOLVED, HTTP 409)."
    """
    env = trigger_anomaly_cascade()
    task = validate_success(
        api.auto_assign_task({"city_code": "BJ"}, OPERATOR_HEADERS), 200
    )
    # Linked ticket is OPEN at this point.
    res = api.complete_task(task["id"], OPERATOR_HEADERS, {"cancel": False})
    validate_error(res, "ERR_TICKET_UNRESOLVED")


def test_complete_repair_dispatch_after_ticket_resolved(api):
    """PRD §3.8: "Completing an operator task advances it from ASSIGNED or
    IN_PROGRESS to COMPLETED."
    """
    env = trigger_anomaly_cascade()
    task = validate_success(
        api.auto_assign_task({"city_code": "BJ"}, OPERATOR_HEADERS), 200
    )
    ticket_id = task["linked_repair_ticket_id"]
    api.assign_ticket(ticket_id, OPERATOR_HEADERS)
    api.resolve_ticket(ticket_id, OPERATOR_HEADERS, {"cancel": False})
    res = api.complete_task(task["id"], OPERATOR_HEADERS, {"cancel": False})
    completed = validate_success(res, 200)
    assert completed["status"] == "COMPLETED"


# ---------------------------------------------------------------------------
# Cancel branch (PRD §3.8) — Admin only
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# RBAC on auto-assign (PRD §4 endpoint table)
# ---------------------------------------------------------------------------


def test_admin_cannot_auto_assign(api, admin_headers):
    """PRD §4 endpoint table: POST /operator-tasks/auto-assign is Operator-only."""
    res = api.auto_assign_task({"city_code": "BJ"}, admin_headers)
    validate_error(res, "ERR_FORBIDDEN")
