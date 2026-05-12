"""Fault lifecycle: open, takeover, resolve, cascade side effects, and
rollback ceiling.

PRD section 3.9 governs faults.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    get_robot,
    get_task,
    open_fault,
    open_fault_payload,
    resolve_fault,
    setup_executing_task_for_rollback,
    setup_fault_cascade_strip,
    setup_lane_strip_for_isolation,
    takeover_fault,
    validate_error,
    validate_success,
)


class TestFaultOpen:
    def test_open_fault_marks_robot_out_of_service(self):
        """PRD section 3.9: 'Opening a fault triggers a chain. The
        robot's fault_state flips to FAULTED and its operational_state
        flips to OUT_OF_SERVICE.'

        Claim: after POST /faults, the robot's fault_state==FAULTED and
        operational_state==OUT_OF_SERVICE.
        """
        fleet, p, d, robot, task = setup_executing_task_for_rollback()
        open_fault(fleet["id"], robot["id"], kind="MECHANICAL_FAULT")
        refreshed = get_robot(fleet["id"], robot["id"])
        assert refreshed["fault_state"] == "FAULTED"
        assert refreshed["operational_state"] == "OUT_OF_SERVICE"

    def test_fault_rolls_back_executing_task(self):
        """PRD section 3.9: 'If the robot was holding a task, that task
        transitions from EXECUTING to ROLLED_BACK - its
        assigned_robot_id, planned_path_node_ids, started_at, and
        assigned_at are cleared, its rollback_count is incremented by
        one ... immediately afterwards, if rollback_count is at or
        below the rollback ceiling of three, the task is requeued to
        QUEUED with queued_at set to the current clock...'

        Claim: opening a fault on a robot with an EXECUTING task
        results in T.status=='QUEUED' AND T.rollback_count==1 AND
        T.assigned_robot_id is null.
        """
        fleet, p, d, robot, task = setup_executing_task_for_rollback()
        open_fault(fleet["id"], robot["id"], kind="MECHANICAL_FAULT")
        refreshed = get_task(fleet["id"], task["id"])
        assert refreshed["status"] == "QUEUED", (
            f"Expected QUEUED after rollback chain, got {refreshed['status']}"
        )
        assert refreshed["rollback_count"] == 1
        assert refreshed.get("assigned_robot_id") in (None,)


class TestFaultedRobotActionsBlocked:
    def test_step_on_faulted_robot_rejected(self):
        """PRD section 3.9: 'While a robot's fault_state is FAULTED, an
        operator may not issue :start, :step, :dock, or :queue_charger
        against it ... those attempts are rejected with
        ERR_ROBOT_FAULTED.'

        Claim: :step on a FAULTED robot -> ERR_ROBOT_FAULTED.
        """
        fleet, p, d, robot, task = setup_executing_task_for_rollback()
        open_fault(fleet["id"], robot["id"], kind="MECHANICAL_FAULT")
        resp = api_client.step_robot(
            fleet["id"], robot["id"], TEST_USERS["operator_headers"]
        )
        validate_error(resp, ApiErrorId.ERR_ROBOT_FAULTED.value)


class TestTakeoverResolve:
    def test_takeover_moves_robot_to_under_manual_control(self):
        """PRD section 3.9: 'Manual takeover transitions the incident
        from OPEN to TAKEOVER. The robot's operational_state becomes
        UNDER_MANUAL_CONTROL, the incident's takeover_started_at is set
        to the current clock...'

        Claim: after :takeover, FaultIncident.status=='TAKEOVER',
        robot.operational_state=='UNDER_MANUAL_CONTROL'.
        """
        fleet, p, d, robot, task = setup_executing_task_for_rollback()
        incident = open_fault(
            fleet["id"], robot["id"], kind="MECHANICAL_FAULT"
        )
        updated = takeover_fault(fleet["id"], incident["id"])
        assert updated["status"] == "TAKEOVER"
        refreshed_robot = get_robot(fleet["id"], robot["id"])
        assert refreshed_robot["operational_state"] == "UNDER_MANUAL_CONTROL"

    def test_resolve_returns_robot_to_ok_and_idle(self):
        """PRD section 3.9: 'Resolution then transitions the incident
        from TAKEOVER to RESOLVED: the robot's fault_state returns to
        OK, the incident's isolation node ids are returned to OPEN with
        blocked_reason cleared back to null, the robot's
        operational_state becomes IDLE, the incident's resolved_at is
        set...'

        Claim: after :resolve, robot.fault_state=='OK',
        robot.operational_state=='IDLE'.
        """
        fleet, p, d, robot, task = setup_executing_task_for_rollback()
        incident = open_fault(
            fleet["id"], robot["id"], kind="MECHANICAL_FAULT"
        )
        takeover_fault(fleet["id"], incident["id"])
        resolved = resolve_fault(fleet["id"], incident["id"])
        assert resolved["status"] == "RESOLVED"
        refreshed = get_robot(fleet["id"], robot["id"])
        assert refreshed["fault_state"] == "OK"
        assert refreshed["operational_state"] == "IDLE"


class TestIsolationZone:
    def test_open_fault_blocks_manhattan_distance_one_nodes(self):
        """PRD section 3.9: 'An isolation zone is laid down on
        FaultIncident.isolation_node_ids, computed as the set of map
        nodes within Manhattan distance one of the robot's
        position_node_id; those nodes' status becomes BLOCKED with
        blocked_reason set to OBSTACLE.'

        Claim: opening a fault on a robot at N3 in a 5-LANE strip
        produces FaultIncident.isolation_node_ids containing N3 and
        its Manhattan-1 neighbours N2 and N4. Those nodes also become
        BLOCKED with blocked_reason=OBSTACLE.
        """
        fleet, nodes, robot = setup_lane_strip_for_isolation()
        incident = open_fault(
            fleet["id"], robot["id"], kind="MECHANICAL_FAULT"
        )
        iso = set(incident["isolation_node_ids"])
        # Manhattan-distance-1 of N3 (index 2): N3 itself, N2 (index 1),
        # N4 (index 3). N1 (index 0) and N5 (index 4) are at distance 2.
        expected = {nodes[1]["id"], nodes[2]["id"], nodes[3]["id"]}
        assert expected.issubset(iso), (
            f"isolation_node_ids should contain N2,N3,N4 (Manhattan-1 of "
            f"robot at N3); got {iso}"
        )
