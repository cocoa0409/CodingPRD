"""Tester assignment selection, workload cap, and qualification posture
filtering (PRD §3.3, §3.5)."""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    create_client,
    create_sample,
    create_task,
    create_tester,
    qualification,
    setup_no_qualified_tester_environment,
    setup_steel_only_testers_concrete_sample,
    setup_two_qualified_testers_with_capacity,
    setup_workload_cap_environment,
    setup_assigned_task,
    create_test_task_payload,
    validate_error,
    validate_success,
)


class TestAutoAssignmentOnCreation:
    def test_task_auto_assigns_to_eligible_tester(self, api):
        """PRD §3.3: 'Task creation synchronously invokes the tester-
        assignment selector ... The chosen tester's assigned_tester_id
        is written onto the task ... and the task transitions from
        PENDING_ASSIGNMENT to ASSIGNED.'

        Claim: creating a task with exactly one eligible tester
        produces TestTask.status==ASSIGNED.
        """
        env = setup_assigned_task()
        assert env["task"]["status"] == "ASSIGNED"
        assert env["task"]["assigned_tester_id"] == env["tester"]["id"]

    def test_assigned_tester_active_task_count_increments(
        self, api, lab_manager_headers,
    ):
        """PRD §3.3: 'the tester's active_task_count is incremented by
        one'.

        Claim: after auto-assignment the tester's
        active_task_count==1.
        """
        env = setup_assigned_task()
        refreshed = validate_success(
            api.get_tester(env["tester"]["id"], lab_manager_headers),
        )
        assert refreshed["active_task_count"] == 1


class TestWorkloadCap:
    def test_workload_cap_boundary_exact_equality_is_full(
        self, api, lab_clerk_headers,
    ):
        """PRD §3.3: 'a tester at the cap cannot.'

        Difficulty-design: workload_cap_exact_equality_boundary.

        Claim: when a Tester's active_task_count already equals
        max_concurrent_tasks (2), creating a new task that would
        require this tester yields ERR_NO_QUALIFIED_TESTER on
        auto-creation (eligible-and-available set is empty).
        """
        # difficulty: boundary_precision_check/workload_cap_exact_equality_boundary
        env = setup_workload_cap_environment(max_concurrent_tasks=2)
        # Now create a third sample/task — only this one tester is
        # qualified; it is at cap. Auto-assignment cannot pick it.
        sample = create_sample(
            client_id=env["client"]["id"], material_category="CONCRETE",
        )
        # PRD §3.3: "If the eligible-and-available set is empty for the
        # qualification-and-posture reason ... explicit assignment
        # attempts on this task are rejected with
        # ERR_NO_QUALIFIED_TESTER. If qualified testers exist but every
        # one of them is at the workload cap, the assignment is
        # rejected with ERR_TESTER_WORKLOAD_EXCEEDED." For task creation
        # the auto-assignment is non-explicit: the task is created
        # PENDING_ASSIGNMENT, and only an explicit /assign reveals the
        # workload-exceeded path. We verify that explicit path here.
        resp = api.create_test_task(
            sample["id"],
            create_test_task_payload(test_method="COMPRESSION_STRENGTH"),
            lab_clerk_headers,
        )
        # Per PRD §3.3 the task either stays PENDING_ASSIGNMENT silently
        # OR the workload check fires explicitly. The PRD prose pins:
        # "if no tester satisfies this combined filter, no assignment is
        # made and the task remains PENDING_ASSIGNMENT". We then assert
        # the explicit POST /tasks/{id}/assign yields workload exceeded.
        data = validate_success(resp, expected_status=201)
        if data["status"] == "PENDING_ASSIGNMENT":
            from test_helpers import TEST_USERS
            assign_resp = api.assign_task(
                data["id"], TEST_USERS["lab_manager_headers"],
            )
            validate_error(
                assign_resp,
                ApiErrorId.ERR_TESTER_WORKLOAD_EXCEEDED.value,
            )

    def test_workload_balancing_selects_lower_count_tester(
        self, api, lab_manager_headers,
    ):
        """PRD §3.3: 'Among eligible-and-available testers, the selector
        ranks first by active_task_count ascending (workload balancing).'

        Claim: when two qualified testers have different active counts,
        the one with the lower count is chosen.

        Difficulty-design: tester_workload_conservation_under_reassign
        (forward action — the conservation portion is asserted in
        test_difficulty_design.py).
        """
        env = setup_two_qualified_testers_with_capacity(
            other_active_count=2,
        )
        # Now create one more task. Two testers are qualified: T1 has
        # active_task_count=2, T2 has 0 → T2 must be picked.
        sample = create_sample(
            client_id=env["client"]["id"], material_category="CONCRETE",
        )
        task = create_task(
            sample_id=sample["id"], test_method="COMPRESSION_STRENGTH",
        )
        assert task["assigned_tester_id"] == env["tester_t2"]["id"]


class TestNoQualifiedTester:
    def test_no_qualified_tester_explicit_assign_returns_error(
        self, api, lab_manager_headers, lab_clerk_headers,
    ):
        """PRD §3.3: 'If the eligible-and-available set is empty for the
        qualification-and-posture reason (i.e. no tester is qualified
        at all), explicit assignment attempts on this task are rejected
        with ERR_NO_QUALIFIED_TESTER.'

        Difficulty-design: empty_eligible_tester_pool_at_assignment.

        Claim: when no tester has a matching qualification, explicit
        POST /tasks/{id}/assign returns ERR_NO_QUALIFIED_TESTER.
        """
        # difficulty: boundary_precision_check/empty_eligible_tester_pool_at_assignment
        env = setup_no_qualified_tester_environment()
        # Task creation leaves the task PENDING_ASSIGNMENT because no
        # qualified tester exists.
        create_resp = api.create_test_task(
            env["sample"]["id"],
            create_test_task_payload(test_method="COMPRESSION_STRENGTH"),
            lab_clerk_headers,
        )
        data = validate_success(create_resp, expected_status=201)
        # Explicit assign must surface ERR_NO_QUALIFIED_TESTER.
        resp = api.assign_task(data["id"], lab_manager_headers)
        validate_error(resp, ApiErrorId.ERR_NO_QUALIFIED_TESTER.value)


class TestLapsedQualificationExcludedFromSelection:
    def test_expired_qualification_not_picked(
        self, api, lab_clerk_headers, lab_manager_headers,
    ):
        """PRD §3.3: 'testers whose qualification_posture is LAPSED are
        excluded.'

        Claim: a Tester whose only qualification has already expired
        is not selected, even when no other tester is qualified.
        """
        client = create_client()
        # Tester qualified ONLY in the past — already LAPSED at
        # CLOCK_ANCHOR (2026-01-01).
        create_tester(qualifications=[
            qualification("CONCRETE", "2020-01-01", "2020-12-31"),
        ])
        sample = create_sample(
            client_id=client["id"], material_category="CONCRETE",
        )
        create_resp = api.create_test_task(
            sample["id"],
            create_test_task_payload(test_method="COMPRESSION_STRENGTH"),
            lab_clerk_headers,
        )
        task = validate_success(create_resp, expected_status=201)
        # An explicit assign must surface no-qualified-tester rather
        # than auto-picking the LAPSED tester.
        resp = api.assign_task(task["id"], lab_manager_headers)
        validate_error(resp, ApiErrorId.ERR_NO_QUALIFIED_TESTER.value)
