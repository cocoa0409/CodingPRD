"""Dispatch scheduling, priority_score computation, and priority ageing.

PRD section 3.5 governs dispatch ordering, priority_score, and
robot_selection.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    AGING_BUCKET_SECONDS,
    AGING_BUCKET_WEIGHT,
    ApiErrorId,
    PRIORITY_BASE,
    advance_clock,
    api_client,
    create_fleet,
    create_robot,
    create_task,
    dispatch,
    get_task,
    setup_fleet_with_two_node_map,
)


class TestPriorityScoreBase:
    @pytest.mark.parametrize(
        "priority_class,expected_base",
        [
            ("CRITICAL", 0),
            ("HIGH", 1000),
            ("NORMAL", 2000),
            ("LOW", 3000),
        ],
    )
    def test_priority_score_at_creation_equals_class_base(
        self, priority_class, expected_base
    ):
        """PRD section 3.5: 'The class base is 0 for CRITICAL, 1000 for
        HIGH, 2000 for NORMAL, and 3000 for LOW. The ageing discount is
        the number of complete sixty-second buckets the task has spent
        in QUEUED ... The priority_score is the class base minus that
        discount.'

        Claim: at age=0, priority_score == class_base (discount=0).
        """
        fleet, p, d = setup_fleet_with_two_node_map()
        task = create_task(
            fleet["id"],
            pickup_node_id=p["id"],
            dropoff_node_id=d["id"],
            priority_class=priority_class,
        )
        assert task["priority_score"] == expected_base, (
            f"Expected priority_score={expected_base} for {priority_class} "
            f"at age=0, got {task['priority_score']}"
        )


class TestPriorityScoreAgeing:
    def test_age_below_60_does_not_decrement(self):
        """PRD section 3.5: 'the number of complete sixty-second buckets
        the task has spent in QUEUED - computed as the floor of the
        maximum of zero and the age in seconds...'

        Claim: at age=59s, priority_score is unchanged from class base
        (floor(59/60)=0).
        """
        fleet, p, d = setup_fleet_with_two_node_map()
        task = create_task(
            fleet["id"],
            pickup_node_id=p["id"],
            dropoff_node_id=d["id"],
            priority_class="NORMAL",
        )
        advance_clock(fleet["id"], 59)
        # PRD section 3.5: 'priority_score is an integer scheduling key
        # computed when the task enters QUEUED and again on every clock
        # advancement.'
        refreshed = get_task(fleet["id"], task["id"])
        assert refreshed["priority_score"] == 2000

    def test_age_at_60_decrements_by_ten(self):
        """PRD section 3.5: 'the floor of the maximum of zero and the
        age in seconds (current Fleet.clock_now minus queued_at) divided
        by sixty - multiplied by ten.'

        Claim: at age=60s, priority_score == 2000 - 10 == 1990 (floor(60/60)*10=10).
        """
        fleet, p, d = setup_fleet_with_two_node_map()
        task = create_task(
            fleet["id"],
            pickup_node_id=p["id"],
            dropoff_node_id=d["id"],
            priority_class="NORMAL",
        )
        advance_clock(fleet["id"], 60)
        refreshed = get_task(fleet["id"], task["id"])
        assert refreshed["priority_score"] == 2000 - 10, (
            f"Expected 1990 at age=60, got {refreshed['priority_score']}"
        )


class TestDispatchOrdering:
    def test_dispatch_assigns_lower_priority_score_first(self):
        """PRD section 3.5: 'and orders them by priority_score
        ascending, breaking ties by task id ascending. For each task
        in that order, it attempts to find a robot via robot_selection
        and, if one is found, commits the assignment in place; later
        tasks see the updated robot pool.'

        Claim: with one robot, dispatch over [CRITICAL_task, NORMAL_task]
        assigns the robot to the CRITICAL task.
        """
        fleet, p, d = setup_fleet_with_two_node_map()
        normal = create_task(
            fleet["id"],
            pickup_node_id=p["id"],
            dropoff_node_id=d["id"],
            priority_class="NORMAL",
        )
        critical = create_task(
            fleet["id"],
            pickup_node_id=p["id"],
            dropoff_node_id=d["id"],
            priority_class="CRITICAL",
        )
        robot = create_robot(
            fleet["id"], position_node_id=p["id"], battery_pct=100
        )
        dispatch(fleet["id"])
        crit_after = get_task(fleet["id"], critical["id"])
        norm_after = get_task(fleet["id"], normal["id"])
        assert crit_after["status"] == "ASSIGNED", (
            f"Critical task should be ASSIGNED first, got {crit_after['status']}"
        )
        assert crit_after["assigned_robot_id"] == robot["id"]
        assert norm_after["status"] == "QUEUED", (
            f"Normal task should still be QUEUED, got {norm_after['status']}"
        )
