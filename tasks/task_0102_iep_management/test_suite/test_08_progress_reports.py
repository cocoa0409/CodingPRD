"""Goal progress reports — PRD §3.7.

Covers: weighted mastery_score formula, tier boundaries (50.00 /
80.00), objective-set parity, duplicate (goal, period) rejection, and
append-only shape.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    MASTERED_THRESHOLD,
    PROGRESSING_THRESHOLD,
    assert_progress_report,
    create_progress_report,
    create_progress_report_payload,
    get_goal,
    make_objective,
    setup_active_iep,
    validate_error,
    validate_success,
)


class TestMasteryWeightedFormula:
    """PRD §3.7: weighted mastery score and tier boundaries."""

    def test_mastery_score_weighted_sum(self, api):
        """PRD §3.7: "each objective contributes its weight
        multiplied by its latest_progress_percent, the products are
        summed, and the total is rounded half-up to two decimal
        places."

        Claim: weights 0.4/0.4/0.2 × progress 60/50/30 =
        24+20+6 = 50.00 → tier PROGRESSING (boundary inclusive).
        """
        objectives = [
            make_objective(objective_id="o1", weight=0.4),
            make_objective(objective_id="o2", weight=0.4),
            make_objective(objective_id="o3", weight=0.2),
        ]
        district, student, _eval, iep, goal = setup_active_iep(
            objectives=objectives,
        )
        create_progress_report(
            district["id"], student["id"], iep["id"], goal["id"],
            reporting_period_index=1,
            objective_progress=[
                {"objective_id": "o1", "progress_percent": 60},
                {"objective_id": "o2", "progress_percent": 50},
                {"objective_id": "o3", "progress_percent": 30},
            ],
        )
        g_now = get_goal(
            district["id"], student["id"], iep["id"], goal["id"],
        )
        # 0.4*60 + 0.4*50 + 0.2*30 = 24 + 20 + 6 = 50.00 exactly.
        assert g_now["mastery_score"] == pytest.approx(50.00, abs=0.01)
        assert g_now["mastery_tier"] == "PROGRESSING"

    def test_mastery_tier_mastered_at_80(self, api):
        """PRD §3.7: "a score of at least 80.00 yields MASTERED".

        Claim: progress 80 across an evenly weighted objective →
        mastery_score=80.00 exactly → MASTERED.
        """
        objectives = [make_objective(objective_id="o1", weight=1.0)]
        district, student, _eval, iep, goal = setup_active_iep(
            objectives=objectives,
        )
        create_progress_report(
            district["id"], student["id"], iep["id"], goal["id"],
            reporting_period_index=1,
            objective_progress=[
                {"objective_id": "o1", "progress_percent": 80},
            ],
        )
        g_now = get_goal(
            district["id"], student["id"], iep["id"], goal["id"],
        )
        assert g_now["mastery_score"] == pytest.approx(80.00, abs=0.01)
        assert g_now["mastery_tier"] == "MASTERED"

    def test_mastery_tier_insufficient_below_50(self, api):
        """PRD §3.7: "a score strictly less than 50.00 yields
        INSUFFICIENT_PROGRESS".

        Claim: progress 49 → score 49.00 → INSUFFICIENT_PROGRESS.
        """
        objectives = [make_objective(objective_id="o1", weight=1.0)]
        district, student, _eval, iep, goal = setup_active_iep(
            objectives=objectives,
        )
        create_progress_report(
            district["id"], student["id"], iep["id"], goal["id"],
            reporting_period_index=1,
            objective_progress=[
                {"objective_id": "o1", "progress_percent": 49},
            ],
        )
        g_now = get_goal(
            district["id"], student["id"], iep["id"], goal["id"],
        )
        assert g_now["mastery_score"] == pytest.approx(49.00, abs=0.01)
        assert g_now["mastery_tier"] == "INSUFFICIENT_PROGRESS"


class TestObjectiveSetParity:
    """PRD §3.7."""

    def test_progress_missing_objective_rejected(self, api):
        """PRD §3.7: "objective_progress must include exactly the
        set of objective_id values declared on the parent goal — no
        missing entries and no extra entries; mismatch is rejected
        with ERR_PROGRESS_OBJECTIVE_SET_MISMATCH."

        Claim: omitting one of the goal's objectives →
        ERR_PROGRESS_OBJECTIVE_SET_MISMATCH.
        """
        objectives = [
            make_objective(objective_id="o1", weight=0.5),
            make_objective(objective_id="o2", weight=0.5),
        ]
        district, student, _eval, iep, goal = setup_active_iep(
            objectives=objectives,
        )
        from test_helpers import TEST_USERS
        res = api.create_progress_report(
            district["id"], student["id"], iep["id"], goal["id"],
            create_progress_report_payload(
                reporting_period_index=1,
                objective_progress=[
                    {"objective_id": "o1", "progress_percent": 50},
                ],
            ),
            TEST_USERS["teacher_headers"],
        )
        validate_error(res, "ERR_PROGRESS_OBJECTIVE_SET_MISMATCH")

    def test_progress_extra_objective_rejected(self, api):
        """PRD §3.7: "no missing entries and no extra entries;
        mismatch is rejected with ERR_PROGRESS_OBJECTIVE_SET_MISMATCH."

        Claim: including an objective_id not on the goal →
        ERR_PROGRESS_OBJECTIVE_SET_MISMATCH.
        """
        objectives = [make_objective(objective_id="o1", weight=1.0)]
        district, student, _eval, iep, goal = setup_active_iep(
            objectives=objectives,
        )
        from test_helpers import TEST_USERS
        res = api.create_progress_report(
            district["id"], student["id"], iep["id"], goal["id"],
            create_progress_report_payload(
                reporting_period_index=1,
                objective_progress=[
                    {"objective_id": "o1", "progress_percent": 50},
                    {"objective_id": "extra", "progress_percent": 50},
                ],
            ),
            TEST_USERS["teacher_headers"],
        )
        validate_error(res, "ERR_PROGRESS_OBJECTIVE_SET_MISMATCH")


class TestProgressReportUniqueness:

    def test_duplicate_progress_report_rejected(self, api):
        """PRD §3.7: "the pair (iep_goal_id, reporting_period_index)
        must be unique system-wide; a duplicate is rejected with
        ERR_DUPLICATE_PROGRESS_REPORT."

        Claim: filing two reports on the same (goal, period) → the
        second fails.
        """
        objectives = [make_objective(objective_id="o1", weight=1.0)]
        district, student, _eval, iep, goal = setup_active_iep(
            objectives=objectives,
        )
        create_progress_report(
            district["id"], student["id"], iep["id"], goal["id"],
            reporting_period_index=1,
            objective_progress=[
                {"objective_id": "o1", "progress_percent": 50},
            ],
        )
        from test_helpers import TEST_USERS
        res = api.create_progress_report(
            district["id"], student["id"], iep["id"], goal["id"],
            create_progress_report_payload(
                reporting_period_index=1,
                objective_progress=[
                    {"objective_id": "o1", "progress_percent": 70},
                ],
            ),
            TEST_USERS["teacher_headers"],
        )
        validate_error(res, "ERR_DUPLICATE_PROGRESS_REPORT")


class TestProgressReportAppendOnlyShape:

    def test_progress_report_lacks_updated_at_and_version(self, api):
        """PRD §2.4: "Two entity types are append-only event records
        and therefore do not carry updated_at or version:
        ParentalConsent ... and GoalProgressReport (each report covers
        a distinct reporting window and is never edited)."

        Claim: GoalProgressReport response carries id + created_at
        but does NOT carry updated_at or version.
        """
        objectives = [make_objective(objective_id="o1", weight=1.0)]
        district, student, _eval, iep, goal = setup_active_iep(
            objectives=objectives,
        )
        from test_helpers import TEST_USERS
        res = api.create_progress_report(
            district["id"], student["id"], iep["id"], goal["id"],
            create_progress_report_payload(
                reporting_period_index=1,
                objective_progress=[
                    {"objective_id": "o1", "progress_percent": 50},
                ],
            ),
            TEST_USERS["teacher_headers"],
        )
        data = validate_success(res, expected_status=201)
        assert_progress_report(data)
        assert "updated_at" not in data, (
            "GoalProgressReport must not carry updated_at per PRD §2.4"
        )
        assert "version" not in data, (
            "GoalProgressReport must not carry version per PRD §2.4"
        )
