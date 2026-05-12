"""Direct :assign business-rule validation: battery, busy, no_path,
isolation, task-already-assigned.

PRD section 3.5 governs the direct-assign gate.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    assign_task,
    assign_task_payload,
    cancel_task,
    create_fleet,
    create_map_edge,
    create_map_node,
    create_robot,
    create_task,
    open_fault,
    setup_assignable_scenario,
    setup_fleet_with_two_node_map,
    validate_error,
)


class TestAssignBattery:
    def test_assign_at_low_threshold_rejected(self):
        """PRD section 3.5: 'targeting a robot whose battery_pct is not
        strictly greater than Fleet.charging_low_threshold_pct yields
        ERR_BATTERY_LOW.'

        Claim: at default low_threshold=20, a robot with battery_pct=20
        is REJECTED with ERR_BATTERY_LOW (boundary: 20 > 20 is false).
        """
        fleet, p, d = setup_fleet_with_two_node_map()
        task = create_task(
            fleet["id"], pickup_node_id=p["id"], dropoff_node_id=d["id"]
        )
        robot = create_robot(
            fleet["id"], position_node_id=p["id"], battery_pct=20
        )
        resp = api_client.assign_task(
            fleet["id"], task["id"],
            assign_task_payload(robot_id=robot["id"]),
            TEST_USERS["operator_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_BATTERY_LOW.value)


class TestAssignBusy:
    def test_assign_busy_robot_rejected(self):
        """PRD section 3.5: 'targeting a robot whose current_task_id is
        already set yields ERR_ROBOT_BUSY.'

        Claim: assigning a second task to a robot that already has
        current_task_id set -> ERR_ROBOT_BUSY.
        """
        fleet, p, d, robot, first = setup_assignable_scenario()
        assign_task(fleet["id"], first["id"], robot_id=robot["id"])
        second = create_task(
            fleet["id"], pickup_node_id=p["id"], dropoff_node_id=d["id"]
        )
        resp = api_client.assign_task(
            fleet["id"], second["id"],
            assign_task_payload(robot_id=robot["id"]),
            TEST_USERS["operator_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_ROBOT_BUSY.value)


class TestAssignNoPath:
    def test_assign_without_path_rejected(self):
        """PRD section 3.5: 'targeting a robot when no path exists from
        its position_node_id via the task's pickup to its dropoff over
        open nodes yields ERR_NO_PATH.'

        Claim: with an isolated pickup node (no edges), :assign yields
        ERR_NO_PATH.
        """
        fleet = create_fleet()
        a = create_map_node(fleet["id"], kind="LANE", x=0, y=0)
        b = create_map_node(fleet["id"], kind="LANE", x=1, y=0)
        # NO edges between them.
        robot = create_robot(
            fleet["id"], position_node_id=a["id"], battery_pct=100
        )
        task = create_task(
            fleet["id"], pickup_node_id=a["id"], dropoff_node_id=b["id"]
        )
        resp = api_client.assign_task(
            fleet["id"], task["id"],
            assign_task_payload(robot_id=robot["id"]),
            TEST_USERS["operator_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_NO_PATH.value)


class TestAssignAlreadyAssigned:
    def test_assign_non_queued_task_rejected(self):
        """PRD section 3.5: 'targeting a task whose status has already
        moved off QUEUED yields ERR_TASK_ALREADY_ASSIGNED.'

        Claim: :assign on a task already in ASSIGNED -> ERR_TASK_ALREADY_ASSIGNED.
        """
        fleet, p, d, robot, task = setup_assignable_scenario()
        assign_task(fleet["id"], task["id"], robot_id=robot["id"])
        # Second :assign with a different robot
        robot2 = create_robot(
            fleet["id"], position_node_id=p["id"], battery_pct=100
        )
        resp = api_client.assign_task(
            fleet["id"], task["id"],
            assign_task_payload(robot_id=robot2["id"]),
            TEST_USERS["operator_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_TASK_ALREADY_ASSIGNED.value)


class TestAssignIsolationViolation:
    def test_assign_into_isolation_zone_rejected(self):
        """PRD section 3.1: 'An assignment whose pickup or dropoff lies
        inside an active fault-incident isolation zone - the set of
        nodes flagged BLOCKED because of an open or in-takeover
        FaultIncident - is rejected with ERR_ISOLATION_VIOLATION
        (HTTP 409).'

        Claim: open a fault on a robot positioned at N3 (LANE strip);
        nodes within Manhattan distance 1 of N3 become BLOCKED with
        OBSTACLE; an :assign with pickup or dropoff inside that
        isolation zone is rejected with ERR_ISOLATION_VIOLATION.
        """
        from test_helpers import setup_lane_strip_for_isolation
        fleet, nodes, fault_robot = setup_lane_strip_for_isolation()
        # Open the fault.
        open_fault(fleet["id"], fault_robot["id"], kind="MECHANICAL_FAULT")
        # Now create a second, healthy robot far from the isolation and
        # attempt to assign it a task whose pickup is the now-isolated
        # node nodes[2] (which is in the isolation zone).
        # We need to place this robot somewhere with a path to the
        # isolated node before the isolation. Since edges are
        # bidirectional, we can put the spare on nodes[0] but the
        # planning happens over OPEN nodes only and will fail with
        # ERR_NO_PATH or ERR_ISOLATION_VIOLATION. We'll assert
        # ERR_ISOLATION_VIOLATION because PRD prose names that exact
        # error for the pickup-in-isolation case.
        spare = create_robot(
            fleet["id"], position_node_id=nodes[0]["id"], battery_pct=100
        )
        task = create_task(
            fleet["id"], pickup_node_id=nodes[2]["id"],
            dropoff_node_id=nodes[0]["id"],
        )
        resp = api_client.assign_task(
            fleet["id"], task["id"],
            assign_task_payload(robot_id=spare["id"]),
            TEST_USERS["operator_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_ISOLATION_VIOLATION.value)
