"""Task splitting, merging, and parent aggregation.

PRD section 3.3 governs splitting, merging, and parent_task_status
aggregation (persisted vs projected views).
"""
from __future__ import annotations

import math

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assign_task,
    cancel_task,
    complete_task,
    create_fleet,
    create_task,
    get_success_data,
    get_task,
    list_tasks,
    merge_tasks_payload,
    setup_assignable_scenario,
    setup_fleet_with_two_node_map,
    setup_oversized_queued_task,
    setup_parent_with_three_children_one_completed,
    start_task,
    step_until_at,
    validate_error,
    validate_success,
)


def _children_of(fleet_id: str, parent_id: str):
    """List children of a parent task using the list endpoint."""
    # PRD section 4 supports filtering by status/source/priority_class
    # but not by parent_task_id. We fetch all tasks and filter
    # client-side.
    tasks = list_tasks(fleet_id)
    return [t for t in tasks if t.get("parent_task_id") == parent_id]


class TestSplit:
    def test_split_creates_expected_number_of_children(self):
        """PRD section 3.3: 'The system creates N child rows where N is
        the ceiling of payload_units divided by max_units_per_robot...'

        Claim: payload_units=23 / max=5 -> ceil(23/5) == 5 children.
        """
        fleet, p, d, task = setup_oversized_queued_task(
            payload_units=23, max_units_per_robot=5
        )
        resp = api_client.split_task(
            fleet["id"], task["id"], TEST_USERS["operator_headers"]
        )
        validate_success(resp, expected_status=200)
        children = _children_of(fleet["id"], task["id"])
        assert len(children) == 5, (
            f"Expected ceil(23/5)=5 children, got {len(children)}"
        )

    def test_split_conserves_payload_units(self):
        """PRD section 3.3: 'divide payload_units evenly with the final
        child absorbing the remainder so that the sum across children
        equals the parent's payload_units.'

        Claim: sum of children's payload_units == parent's payload_units.
        """
        fleet, p, d, parent = setup_oversized_queued_task(
            payload_units=23, max_units_per_robot=5
        )
        api_client.split_task(
            fleet["id"], parent["id"], TEST_USERS["operator_headers"]
        )
        children = _children_of(fleet["id"], parent["id"])
        assert sum(c["payload_units"] for c in children) == 23

    def test_split_parent_stays_queued(self):
        """PRD section 3.3: 'The parent itself remains in QUEUED but is
        excluded from dispatch...'

        Claim: after split, parent.status is still QUEUED.
        """
        fleet, p, d, parent = setup_oversized_queued_task(
            payload_units=23, max_units_per_robot=5
        )
        api_client.split_task(
            fleet["id"], parent["id"], TEST_USERS["operator_headers"]
        )
        refreshed = get_task(fleet["id"], parent["id"])
        assert refreshed["status"] == "QUEUED"

    def test_split_with_payload_below_max_rejected(self):
        """PRD section 3.3: 'A task whose payload_units exceeds its
        max_units_per_robot may be split by an Operator.' and 'A split
        request that fails any of these preconditions is rejected with
        ERR_SPLIT_NOT_APPLICABLE (HTTP 422).'

        Claim: payload_units==max_units_per_robot does NOT 'exceed' the
        ceiling, so :split is rejected with ERR_SPLIT_NOT_APPLICABLE.
        """
        fleet, p, d = setup_fleet_with_two_node_map()
        task = create_task(
            fleet["id"], pickup_node_id=p["id"], dropoff_node_id=d["id"],
            payload_units=5, max_units_per_robot=5,
        )
        resp = api_client.split_task(
            fleet["id"], task["id"], TEST_USERS["operator_headers"]
        )
        validate_error(resp, ApiErrorId.ERR_SPLIT_NOT_APPLICABLE.value)


class TestMerge:
    def test_merge_compatible_tasks_succeeds(self):
        """PRD section 3.3: 'Merging takes two QUEUED tasks identified
        by task_id_a and task_id_b and combines them. The merge is legal
        only when both tasks share the same source, the same
        priority_class, the same pickup_node_id, and the same
        dropoff_node_id; neither task has a parent_task_id; and the
        combined payload_units is no greater than the max_units_per_robot
        of the surviving task.'

        Claim: two QUEUED tasks with matching source/priority/pickup/
        dropoff can merge; the loser becomes MERGED.
        """
        fleet, p, d = setup_fleet_with_two_node_map()
        a = create_task(
            fleet["id"], pickup_node_id=p["id"], dropoff_node_id=d["id"],
            payload_units=2, max_units_per_robot=10,
            priority_class="NORMAL", source="INBOUND",
        )
        b = create_task(
            fleet["id"], pickup_node_id=p["id"], dropoff_node_id=d["id"],
            payload_units=3, max_units_per_robot=10,
            priority_class="NORMAL", source="INBOUND",
        )
        resp = api_client.merge_tasks(
            fleet["id"],
            merge_tasks_payload(task_id_a=a["id"], task_id_b=b["id"]),
            TEST_USERS["operator_headers"],
        )
        validate_success(resp, expected_status=200)
        # Determine survivor/loser by lexicographic id (PRD section 3.3)
        sid, lid = sorted([a["id"], b["id"]])
        survivor = get_task(fleet["id"], sid)
        loser = get_task(fleet["id"], lid)
        assert loser["status"] == "MERGED", (
            f"Lexicographically larger id ({lid}) should be MERGED, got {loser['status']}"
        )
        assert loser["merged_into_task_id"] == sid
        # PRD section 3.3: 'the survivor's payload_units is incremented by the loser's payload_units'
        assert survivor["payload_units"] == 5, (
            f"Survivor payload_units should be 2+3=5, got {survivor['payload_units']}"
        )

    def test_merge_with_mismatched_source_rejected(self):
        """PRD section 3.3: 'The merge is legal only when both tasks
        share the same source... A merge that violates any compatibility
        rule is rejected with ERR_MERGE_INCOMPATIBLE (HTTP 422).'

        Claim: source mismatch -> ERR_MERGE_INCOMPATIBLE.
        """
        fleet, p, d = setup_fleet_with_two_node_map()
        a = create_task(
            fleet["id"], pickup_node_id=p["id"], dropoff_node_id=d["id"],
            source="INBOUND",
        )
        b = create_task(
            fleet["id"], pickup_node_id=p["id"], dropoff_node_id=d["id"],
            source="OUTBOUND",
        )
        resp = api_client.merge_tasks(
            fleet["id"],
            merge_tasks_payload(task_id_a=a["id"], task_id_b=b["id"]),
            TEST_USERS["operator_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_MERGE_INCOMPATIBLE.value)

    def test_merge_with_combined_units_exceeding_max_rejected(self):
        """PRD section 3.3: 'neither task has a parent_task_id; and
        the combined payload_units is no greater than the
        max_units_per_robot of the surviving task.'

        Claim: 4+8=12 with max_units_per_robot=10 on survivor ->
        ERR_MERGE_INCOMPATIBLE.
        """
        fleet, p, d = setup_fleet_with_two_node_map()
        a = create_task(
            fleet["id"], pickup_node_id=p["id"], dropoff_node_id=d["id"],
            payload_units=4, max_units_per_robot=10,
        )
        b = create_task(
            fleet["id"], pickup_node_id=p["id"], dropoff_node_id=d["id"],
            payload_units=8, max_units_per_robot=10,
        )
        resp = api_client.merge_tasks(
            fleet["id"],
            merge_tasks_payload(task_id_a=a["id"], task_id_b=b["id"]),
            TEST_USERS["operator_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_MERGE_INCOMPATIBLE.value)


class TestParentAggregation:
    def test_parent_persisted_status_remains_queued_with_non_terminal_children(
        self,
    ):
        """PRD section 3.3: 'In every other case the parent stays
        QUEUED.' and 'Reading without view=projected returns the
        persisted aggregated status, which can differ from the
        projection when any child is still non-terminal.'

        Claim: with only one child COMPLETED and two QUEUED, the parent's
        persisted status (no ?view) is QUEUED.
        """
        fleet, p, d, children, parent = (
            setup_parent_with_three_children_one_completed()
        )
        refreshed = get_task(fleet["id"], parent["id"])
        assert refreshed["status"] == "QUEUED", (
            f"Persisted parent status should be QUEUED while children are "
            f"non-terminal, got {refreshed['status']}"
        )
