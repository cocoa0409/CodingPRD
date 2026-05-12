"""Task state machine: QUEUED -> ASSIGNED -> EXECUTING -> COMPLETED, plus
:cancel from each pre-terminal state.

PRD section 3.2 governs the task lifecycle.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_clock,
    api_client,
    assign_task,
    assign_task_payload,
    cancel_task,
    complete_task,
    create_fleet,
    create_task,
    find_audit_events,
    get_robot,
    get_task,
    list_audit_events,
    setup_assignable_scenario,
    setup_executing_task,
    setup_fleet_with_two_node_map,
    start_task,
    step_until_at,
    validate_error,
    validate_success,
)


# ===========================================================================
# Happy path
# ===========================================================================
class TestHappyPath:
    def test_task_created_in_queued(self, fleet_admin_headers, operator_headers):
        """PRD section 3.2: 'A task is created in QUEUED by either an
        Operator or a WMS integrator...'

        Claim: a freshly created task has status='QUEUED' and a
        queued_at timestamp.
        """
        fleet, p, d, robot, task = setup_assignable_scenario()
        assert task["status"] == "QUEUED"
        assert task["queued_at"]

    def test_direct_assign_walks_to_assigned(self):
        """PRD section 3.2: 'When the scheduler runs (see section 3.5)
        or when an operator explicitly assigns a robot to the task, the
        task transitions from QUEUED to ASSIGNED.'

        Claim: :assign moves a QUEUED task to ASSIGNED with
        assigned_robot_id set.
        """
        fleet, p, d, robot, task = setup_assignable_scenario()
        assigned = assign_task(fleet["id"], task["id"], robot_id=robot["id"])
        assert assigned["status"] == "ASSIGNED"
        assert assigned["assigned_robot_id"] == robot["id"]
        assert assigned["assigned_at"]

    def test_start_walks_to_executing_and_records_started_at(self):
        """PRD section 3.2: 'Execution begins by transitioning the task
        from ASSIGNED to EXECUTING ... On success, the robot's
        operational_state flips to EXECUTING, the task's started_at is
        recorded, and an audit row is written.'

        Claim: :start sets status=EXECUTING, started_at, and the robot's
        operational_state=EXECUTING.
        """
        fleet, p, d, robot, started = setup_executing_task()
        assert started["status"] == "EXECUTING"
        assert started["started_at"]
        refreshed_robot = get_robot(fleet["id"], robot["id"])
        assert refreshed_robot["operational_state"] == "EXECUTING"

    def test_complete_at_dropoff_walks_to_completed(self):
        """PRD section 3.2: 'Completion fires when the task is in
        EXECUTING and the assigned robot's position_node_id equals the
        task's dropoff_node_id. The task's completed_at is set, the
        robot's operational_state returns to IDLE, the robot's
        current_task_id is cleared...'

        Claim: when robot reaches dropoff and :complete is called,
        task.status==COMPLETED, completed_at is set, robot is IDLE with
        current_task_id null.
        """
        fleet, p, d, robot, task = setup_executing_task()
        step_until_at(fleet["id"], robot, d["id"])
        completed = complete_task(fleet["id"], task["id"])
        assert completed["status"] == "COMPLETED"
        assert completed["completed_at"]
        refreshed_robot = get_robot(fleet["id"], robot["id"])
        assert refreshed_robot["operational_state"] == "IDLE"
        assert refreshed_robot.get("current_task_id") in (None,)


# ===========================================================================
# Cancellation
# ===========================================================================
class TestCancellation:
    def test_cancel_queued_task_succeeds(self):
        """PRD section 3.2: 'Cancellation is allowed from QUEUED,
        ASSIGNED, and EXECUTING.'

        Claim: cancelling a QUEUED task succeeds and writes CANCELLED.
        """
        fleet, p, d, robot, task = setup_assignable_scenario()
        cancelled = cancel_task(fleet["id"], task["id"])
        assert cancelled["status"] == "CANCELLED"

    def test_cancel_executing_clears_robot(self):
        """PRD section 3.2: 'On success, if the task had an assigned
        robot, that robot's current_task_id is cleared and its
        operational_state returns to IDLE...'

        Claim: cancelling an EXECUTING task returns the robot to IDLE
        with current_task_id null.
        """
        fleet, p, d, robot, task = setup_executing_task()
        cancel_task(fleet["id"], task["id"])
        refreshed_robot = get_robot(fleet["id"], robot["id"])
        assert refreshed_robot["operational_state"] == "IDLE"
        assert refreshed_robot.get("current_task_id") in (None,)

    def test_cancel_completed_task_rejected(self):
        """PRD section 3.2: 'Cancellation is allowed from QUEUED,
        ASSIGNED, and EXECUTING.'

        Claim: :cancel on a COMPLETED task -> ERR_INVALID_STATE.
        """
        fleet, p, d, robot, task = setup_executing_task()
        step_until_at(fleet["id"], robot, d["id"])
        complete_task(fleet["id"], task["id"])
        resp = api_client.cancel_task(
            fleet["id"], task["id"], TEST_USERS["operator_headers"]
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Expiry
# ===========================================================================
class TestExpiry:
    def test_queued_task_expires_after_threshold(self):
        """PRD section 3.2: 'Expiry is automatic: a QUEUED task whose
        age — the difference between the current Fleet.clock_now and
        its queued_at in seconds — is at or above the fleet's
        task_expiry_seconds is moved to EXPIRED. The expiry sweep runs
        during clock advancement and during a dispatch pass.'

        Claim: a QUEUED task with age >= task_expiry_seconds (default
        600) becomes EXPIRED after advance_clock.
        """
        fleet, p, d = setup_fleet_with_two_node_map(
            task_expiry_seconds=600
        )
        task = create_task(
            fleet["id"], pickup_node_id=p["id"], dropoff_node_id=d["id"]
        )
        advance_clock(fleet["id"], 600)
        refreshed = get_task(fleet["id"], task["id"])
        assert refreshed["status"] == "EXPIRED", (
            f"Expected EXPIRED at age=600 (>=600), got {refreshed['status']!r}"
        )

    def test_queued_task_below_threshold_stays_queued(self):
        """PRD section 3.2: 'is at or above the fleet's
        task_expiry_seconds is moved to EXPIRED'.

        Claim: a QUEUED task with age=599 stays QUEUED (boundary X-1).
        """
        fleet, p, d = setup_fleet_with_two_node_map(
            task_expiry_seconds=600
        )
        task = create_task(
            fleet["id"], pickup_node_id=p["id"], dropoff_node_id=d["id"]
        )
        advance_clock(fleet["id"], 599)
        refreshed = get_task(fleet["id"], task["id"])
        assert refreshed["status"] == "QUEUED"


# ===========================================================================
# Audit side effect
# ===========================================================================
class TestAuditOnTransitions:
    def test_task_transitions_write_audit_rows(self):
        """PRD section 3.10: 'Every state transition writes a row to
        AuditEvent with event_kind, subject_kind, subject_id, from_state,
        to_state, actor_role, occurred_at, and the owning fleet_id. The
        event_kind is TASK_STATUS for task transitions.'

        Claim: after QUEUED->ASSIGNED->EXECUTING transitions, the audit
        log contains TASK_STATUS rows with matching from_state/to_state.
        """
        fleet, p, d, robot, task = setup_executing_task()
        events = list_audit_events(
            fleet["id"], event_kind="TASK_STATUS", subject_id=task["id"]
        )
        # Expect at least two events: QUEUED->ASSIGNED, ASSIGNED->EXECUTING.
        q2a = find_audit_events(
            events, from_state="QUEUED", to_state="ASSIGNED"
        )
        a2e = find_audit_events(
            events, from_state="ASSIGNED", to_state="EXECUTING"
        )
        assert len(q2a) >= 1, f"Missing QUEUED->ASSIGNED audit for task {task['id']}"
        assert len(a2e) >= 1, f"Missing ASSIGNED->EXECUTING audit for task {task['id']}"
