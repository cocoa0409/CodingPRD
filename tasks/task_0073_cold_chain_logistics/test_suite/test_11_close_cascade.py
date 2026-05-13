"""Task close, cascade-to-CLOSED for resolved alerts (PRD §3.8).

Difficulty-design instances exercised:
- # difficulty: transitive_cascade/close_task_to_resolved_alerts_to_closed
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    DISP,
    TaskParties,
    advance_clock,
    advance_clock_to,
    close_task,
    get_clock_now,
    open_alert_via_reading,
    parse_iso,
    setup_delivered_task,
    setup_delivered_with_alert,
    validate_error,
    validate_success,
    walk_alert_to_resolved,
)


# ===========================================================================
# Close happy path
# ===========================================================================
def test_close_delivered_task_to_closed(api):
    """PRD §3.8: 'A CARRIER closes a task from DELIVERED to CLOSED.'"""
    scenario = setup_delivered_task()
    parties: TaskParties = scenario["parties"]
    task = scenario["task"]
    closed = validate_success(
        api.close_task(task["id"], parties.carrier_h())
    )
    assert closed["status"] == "CLOSED"
    assert closed.get("closed_at") is not None


def test_close_with_open_alert_rejected(api):
    """PRD §3.8: 'The transition is rejected with ERR_INVALID_STATE when
    any alert on the task is still in OPEN, ACKNOWLEDGED, IN_RESPONSE,
    or ESCALATED.'"""
    # PRD §3.5: readings can only be ingested while the task is in
    # DISPATCHED/IN_TRANSIT/AT_STOP, so the second (still-OPEN) alert
    # must be opened *before* the task reaches DELIVERED.
    scenario = setup_delivered_with_alert(
        extra_alerts=[{"breach_temp": -15.00, "keep_open": True}],
    )
    parties: TaskParties = scenario["parties"]
    resp = api.close_task(scenario["task"]["id"], parties.carrier_h())
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Cascade to CLOSED — difficulty
# ===========================================================================
def test_close_cascades_resolved_alerts_to_closed(api):
    """PRD §3.7: 'Once the parent task transitions from DELIVERED to
    CLOSED, every alert on the task whose status is RESOLVED is
    cascaded to CLOSED, with an audit-log entry written for each.'
    PRD §3.8: 'The server stamps closed_at to the current clock and
    cascades any RESOLVED alerts on the task to CLOSED.'

    # difficulty: transitive_cascade/close_task_to_resolved_alerts_to_closed
    """
    # PRD §3.5: readings can only be ingested while the task is in
    # DISPATCHED/IN_TRANSIT/AT_STOP. Open the second alert during transit
    # via the fixture's extra_alerts hook, then walk it to RESOLVED.
    scenario = setup_delivered_with_alert(
        extra_alerts=[{"breach_temp": -15.00}],
    )
    parties: TaskParties = scenario["parties"]
    second_alert = scenario["extra_alerts"][0]
    # Confirm both alerts are RESOLVED before close.
    a1 = validate_success(api.get_alert(scenario["alert"]["id"], DISP))
    a2 = validate_success(api.get_alert(second_alert["id"], DISP))
    assert a1["status"] == "RESOLVED"
    assert a2["status"] == "RESOLVED"
    # Close the task.
    closed = validate_success(
        api.close_task(scenario["task"]["id"], parties.carrier_h())
    )
    assert closed["status"] == "CLOSED"
    assert closed.get("closed_at") is not None, (
        "PRD §3.8: 'The server stamps closed_at to the current clock'"
    )
    # Both alerts cascade to CLOSED.
    a1_after = validate_success(api.get_alert(scenario["alert"]["id"], DISP))
    a2_after = validate_success(api.get_alert(second_alert["id"], DISP))
    assert a1_after["status"] == "CLOSED", (
        "PRD §3.7/§3.8 cascade: RESOLVED -> CLOSED"
    )
    assert a2_after["status"] == "CLOSED", (
        "PRD §3.7/§3.8 cascade: RESOLVED -> CLOSED"
    )


def test_close_cascade_stamps_closed_at_to_current_clock(api):
    """PRD §3.8: 'The server stamps closed_at to the current clock and
    cascades any RESOLVED alerts on the task to CLOSED.'

    This test verifies link 1 (DELIVERED -> CLOSED with closed_at set
    to a value matching the current logical clock) independently of
    the alert cascade. The single resolved alert is also asserted to
    cascade — link 2.

    # difficulty: transitive_cascade/close_task_to_resolved_alerts_to_closed
    """
    scenario = setup_delivered_with_alert()
    parties: TaskParties = scenario["parties"]
    pre_clock = parse_iso(get_clock_now())
    closed = validate_success(
        api.close_task(scenario["task"]["id"], parties.carrier_h())
    )
    # Link 1: task is CLOSED with closed_at set.
    assert closed["status"] == "CLOSED"
    assert closed.get("closed_at") is not None
    closed_at = parse_iso(closed["closed_at"])
    # closed_at must be at-or-after pre-call clock.
    assert closed_at >= pre_clock, (
        "PRD §3.8: 'The server stamps closed_at to the current clock'"
    )
    # Link 2: the resolved alert cascades to CLOSED.
    alert_after = validate_success(
        api.get_alert(scenario["alert"]["id"], DISP)
    )
    assert alert_after["status"] == "CLOSED"


def test_close_task_terminal_no_further_transitions(api):
    """PRD §3.8: 'Tasks reach the terminal CLOSED and ABORTED states by
    these paths only.'"""
    scenario = setup_delivered_task()
    parties: TaskParties = scenario["parties"]
    closed = close_task(scenario)["task"]
    assert closed["status"] == "CLOSED"
    # A second close call (or any subsequent state transition) MUST
    # be rejected.
    resp = api.close_task(closed["id"], parties.carrier_h())
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
