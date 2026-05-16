"""IEP goals — PRD §3.3, §3.5 (close), §3.7 (mastery from objectives).

Covers: objective weight validation, goal creation, close MET (gated
by mastery), close NOT_MET, parent-IEP-must-be-ACTIVE check.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    assert_iep_goal,
    assert_objective_weights_sum_to_one,
    begin_amendment,
    close_goal_payload,
    create_goal_payload,
    create_goal_with_objectives,
    create_goal_with_single_objective,
    create_progress_report,
    get_goal,
    make_objective,
    setup_active_iep,
    setup_eligible_student,
    validate_error,
    validate_success,
)


class TestGoalCreation:

    def test_create_goal_starts_in_proposed(self, api, teacher_headers):
        """PRD §3.3: "it begins life in PROPOSED".

        Claim: a freshly created goal under a DRAFT IEP is in
        PROPOSED.
        """
        from test_helpers import create_iep
        _district, student, _eval = setup_eligible_student()
        iep = create_iep(student["district_id"], student["id"])
        goal = create_goal_with_single_objective(
            student["district_id"], student["id"], iep["id"],
        )
        assert_iep_goal(goal)
        assert goal["status"] == "PROPOSED"
        assert goal["mastery_score"] == 0
        # PRD §3.7: a score strictly less than 50.00 yields
        # INSUFFICIENT_PROGRESS, so the initial tier on a fresh
        # goal with 0 progress is INSUFFICIENT_PROGRESS.
        assert goal["mastery_tier"] == "INSUFFICIENT_PROGRESS"


class TestObjectiveWeightValidation:
    """PRD §3.3, §1.4 priority 16."""

    @pytest.mark.parametrize(
        "objectives,description",
        [
            ([make_objective(weight=0.5),
              make_objective(weight=0.4)], "sum<1.00"),
            ([make_objective(weight=0.5),
              make_objective(weight=0.6)], "sum>1.00"),
            ([make_objective(weight=0.0)], "weight=0"),
            ([make_objective(weight=1.1)], "weight>1"),
        ],
    )
    def test_objective_weights_outside_valid_range_rejected(
        self, api, teacher_headers, objectives, description,
    ):
        """PRD §3.3: "the sum of all objective weight values on a
        goal must equal exactly 1.00 when rounded half-up to two
        decimal places; otherwise the goal create or update is
        rejected with ERR_OBJECTIVE_WEIGHTS_INVALID."
        PRD §3.3: "a weight strictly greater than zero and less than
        or equal to one".

        Claim ({description}): each invalid weight configuration is
        rejected with ERR_OBJECTIVE_WEIGHTS_INVALID.
        """
        from test_helpers import create_iep
        _district, student, _eval = setup_eligible_student()
        iep = create_iep(student["district_id"], student["id"])
        res = api.create_goal(
            student["district_id"], student["id"], iep["id"],
            create_goal_payload(objectives=objectives),
            teacher_headers,
        )
        validate_error(res, "ERR_OBJECTIVE_WEIGHTS_INVALID")

    def test_valid_weights_accepted(self, api, teacher_headers):
        """PRD §3.3: "the sum of all objective weight values on a
        goal must equal exactly 1.00".

        Claim: weights summing to 1.00 with each in (0, 1] are
        accepted.
        """
        from test_helpers import create_iep
        _district, student, _eval = setup_eligible_student()
        iep = create_iep(student["district_id"], student["id"])
        objectives = [
            make_objective(weight=0.4),
            make_objective(weight=0.4),
            make_objective(weight=0.2),
        ]
        assert_objective_weights_sum_to_one(objectives)
        goal = create_goal_with_objectives(
            student["district_id"], student["id"], iep["id"],
            objectives=objectives,
        )
        assert len(goal["objectives"]) == 3


class TestGoalCloseMet:
    """PRD §3.5 ACTIVE → MET."""

    def test_close_met_when_mastered_succeeds(self, api):
        """PRD §3.5: "Closing as MET additionally requires that the
        goal's mastery_tier currently equal MASTERED".

        Setup: create a goal with one objective; file a progress
        report with progress 100 so mastery_score=100 and
        mastery_tier=MASTERED; then close as MET.
        """
        district, student, _eval, iep, goal = setup_active_iep()
        # The default goal has one objective with weight=1.0.
        obj_id = goal["objectives"][0]["objective_id"]
        create_progress_report(
            district["id"], student["id"], iep["id"], goal["id"],
            reporting_period_index=1,
            objective_progress=[
                {"objective_id": obj_id, "progress_percent": 100},
            ],
        )
        from test_helpers import TEST_USERS
        res = api.close_goal(
            district["id"], student["id"], iep["id"], goal["id"],
            close_goal_payload(disposition="MET"),
            TEST_USERS["teacher_headers"],
        )
        validate_success(res, expected_status=200)
        g_now = get_goal(
            district["id"], student["id"], iep["id"], goal["id"],
        )
        assert g_now["status"] == "MET"

    def test_close_met_when_not_mastered_rejected(self, api):
        """PRD §3.5: "if mastery is insufficient the request is
        rejected with ERR_GOAL_NOT_MASTERED".

        Claim: closing as MET when mastery_tier !=
        MASTERED → ERR_GOAL_NOT_MASTERED.
        """
        district, student, _eval, iep, goal = setup_active_iep()
        from test_helpers import TEST_USERS
        # mastery_score is 0 → mastery_tier=INSUFFICIENT_PROGRESS
        res = api.close_goal(
            district["id"], student["id"], iep["id"], goal["id"],
            close_goal_payload(disposition="MET"),
            TEST_USERS["teacher_headers"],
        )
        validate_error(res, "ERR_GOAL_NOT_MASTERED")


class TestGoalCloseNotMet:
    """PRD §3.5 ACTIVE → NOT_MET."""

    def test_close_not_met_does_not_require_mastery(self, api):
        """PRD §3.5: "Closing as NOT_MET requires only the
        goal-in-ACTIVE and parent-IEP-in-ACTIVE conditions; mastery
        is not required."

        Claim: closing as NOT_MET succeeds even at mastery=0.
        """
        district, student, _eval, iep, goal = setup_active_iep()
        from test_helpers import TEST_USERS
        res = api.close_goal(
            district["id"], student["id"], iep["id"], goal["id"],
            close_goal_payload(disposition="NOT_MET"),
            TEST_USERS["teacher_headers"],
        )
        validate_success(res, expected_status=200)
        g_now = get_goal(
            district["id"], student["id"], iep["id"], goal["id"],
        )
        assert g_now["status"] == "NOT_MET"


class TestGoalCloseParentIepGate:
    """PRD §3.5 parent IEP must be ACTIVE."""

    def test_close_when_parent_iep_in_amendment_pending_rejected(
        self, api,
    ):
        """PRD §3.5: "if the parent IEP is not in ACTIVE (for
        example, it is in AMENDMENT_PENDING) the request is rejected
        with ERR_IEP_NOT_ACTIVE".

        Claim: closing a goal whose parent IEP is in
        AMENDMENT_PENDING → ERR_IEP_NOT_ACTIVE.
        """
        district, student, _eval, iep, goal = setup_active_iep()
        begin_amendment(district["id"], student["id"], iep["id"])
        from test_helpers import TEST_USERS
        res = api.close_goal(
            district["id"], student["id"], iep["id"], goal["id"],
            close_goal_payload(disposition="NOT_MET"),
            TEST_USERS["teacher_headers"],
        )
        validate_error(res, "ERR_IEP_NOT_ACTIVE")
