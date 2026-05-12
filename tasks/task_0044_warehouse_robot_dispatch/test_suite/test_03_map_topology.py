"""Map node and edge creation, blocked-reason semantics, and the
bidirectional-edge materialisation rule.

PRD section 3.1 governs all node/edge behaviour.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_map_edge,
    assert_map_node,
    create_fleet,
    create_map_edge,
    create_map_node,
    create_map_node_payload,
    list_robots,
    setup_empty_fleet,
    validate_error,
    validate_success,
)


class TestMapNodeCreation:
    def test_lane_node_status_starts_open_blocked_reason_null(
        self, fleet_admin_headers
    ):
        """PRD section 3.1: 'Every node's status is initially OPEN; when
        the system or an external event drives it to BLOCKED, the reason
        is recorded on blocked_reason...'

        Claim: a freshly created node has status='OPEN' and
        blocked_reason is null.
        """
        fleet = create_fleet(headers=fleet_admin_headers)
        node = create_map_node(
            fleet["id"], kind="LANE", x=0, y=0, headers=fleet_admin_headers
        )
        assert_map_node(node)
        assert node["status"] == "OPEN"
        assert node.get("blocked_reason") is None

    def test_intersection_node_kind_accepted(self, fleet_admin_headers):
        """PRD section 3.1: 'kind drawn from the closed set LANE,
        INTERSECTION, LIFT_POINT, CHARGER, PARK, and SHELF.'

        Claim: kind='INTERSECTION' creates a node.
        """
        fleet = create_fleet(headers=fleet_admin_headers)
        node = create_map_node(
            fleet["id"], kind="INTERSECTION", x=0, y=0,
            headers=fleet_admin_headers,
        )
        assert node["kind"] == "INTERSECTION"

    def test_node_kinds_with_pinned_capacity_one(self, fleet_admin_headers):
        """PRD section 3.1: 'INTERSECTION, LIFT_POINT, and CHARGER nodes
        always carry a capacity of 1 (single-occupant by design)...'

        Claim: INTERSECTION node defaults to capacity=1.
        """
        fleet = create_fleet(headers=fleet_admin_headers)
        for kind in ("INTERSECTION", "LIFT_POINT", "CHARGER"):
            node = create_map_node(
                fleet["id"], kind=kind, x=0, y=0,
                headers=fleet_admin_headers,
            )
            assert node["capacity"] == 1, (
                f"{kind} should have capacity=1, got {node['capacity']}"
            )


class TestMapEdgeBidirectionalMaterialisation:
    def test_non_directional_edge_creates_reverse(self, fleet_admin_headers):
        """PRD section 3.1: 'an edge whose directional flag is false
        is logically two-way, and the system materialises a reverse
        MapEdge row at creation time so that downstream path planning
        treats both directions symmetrically.'

        Claim: creating a non-directional edge a->b causes a reverse
        b->a edge to be materialised. We verify behaviour by routing
        a robot in both directions via /dispatch+/assign on a 3-node
        graph (this is the observable consequence the PRD states).
        """
        fleet = create_fleet(headers=fleet_admin_headers)
        a = create_map_node(
            fleet["id"], kind="LANE", x=0, y=0, headers=fleet_admin_headers
        )
        b = create_map_node(
            fleet["id"], kind="LANE", x=1, y=0, headers=fleet_admin_headers
        )
        # Create only ONE non-directional edge a<->b.
        create_map_edge(
            fleet["id"],
            from_node_id=a["id"],
            to_node_id=b["id"],
            cost=1,
            directional=False,
            headers=fleet_admin_headers,
        )
        # Task with pickup=B and dropoff=A requires the reverse edge.
        from test_helpers import (
            assign_task, create_robot, create_task, dispatch, get_task,
        )
        robot = create_robot(
            fleet["id"], position_node_id=a["id"], battery_pct=100,
            headers=fleet_admin_headers,
        )
        # Pickup=B, dropoff=A: planning requires A->B->A, where B->A is
        # only possible if the reverse was materialised.
        task = create_task(
            fleet["id"], pickup_node_id=b["id"], dropoff_node_id=a["id"]
        )
        assign_task(fleet["id"], task["id"], robot_id=robot["id"])
        refreshed = get_task(fleet["id"], task["id"])
        assert refreshed["status"] == "ASSIGNED", (
            f"Expected ASSIGNED (proves bidirectional materialisation), "
            f"got {refreshed['status']!r}"
        )
        assert refreshed["assigned_robot_id"] == robot["id"]

    def test_directional_edge_no_reverse(self, fleet_admin_headers):
        """PRD section 3.1: 'An edge whose directional flag is true is
        one-way only...'

        Claim: a directional edge a->b alone is NOT sufficient to plan
        a path from b to a; assignment with pickup=B dropoff=A yields
        ERR_NO_PATH.
        """
        from test_helpers import (
            assign_task_payload, create_robot, create_task,
        )
        fleet = create_fleet(headers=fleet_admin_headers)
        a = create_map_node(
            fleet["id"], kind="LANE", x=0, y=0, headers=fleet_admin_headers
        )
        b = create_map_node(
            fleet["id"], kind="LANE", x=1, y=0, headers=fleet_admin_headers
        )
        create_map_edge(
            fleet["id"],
            from_node_id=a["id"],
            to_node_id=b["id"],
            cost=1,
            directional=True,
            headers=fleet_admin_headers,
        )
        robot = create_robot(
            fleet["id"], position_node_id=a["id"], battery_pct=100,
            headers=fleet_admin_headers,
        )
        task = create_task(
            fleet["id"], pickup_node_id=b["id"], dropoff_node_id=a["id"]
        )
        from test_helpers.test_users import TEST_USERS as _TU
        resp = api_client.assign_task(
            fleet["id"], task["id"],
            assign_task_payload(robot_id=robot["id"]),
            _TU["operator_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_NO_PATH.value)
