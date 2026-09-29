"""The worsened-callback variance cascade and its bystander coverage window."""

import pytest

from test_helpers.assertions import assert_instant, assert_nurse_load
from test_helpers.constants import SUSPEND_REASON_COMPLIANCE_REVIEW


@pytest.fixture
def draft_window_and_reached_callback(world):
    """A reached high-risk callback plus an untouched draft coverage window."""
    world.bootstrap(
        clock="2026-08-03T14:30:00Z",
        nurse_keys=("nurse_a", "nurse_c"),
        practice={"variance_review_threshold": 1},
        protocol={"base_severity": 62},
    )
    window = world.create_coverage_window(
        start_utc="2026-08-10T00:00:00Z",
        end_utc="2026-08-11T00:00:00Z",
        coverage_kind="NIGHTS",
    )
    call, assessment, disposition = world.dispositioned_call(
        "ED_NOW", "nurse_a", red_flag_count=1
    )
    task = world.callback_for(disposition["id"])
    world.record_attempt(task["id"], "nurse_a", "REACHED")
    return window, call, disposition, task


class TestWorsenedCallbackEscalatesTheVariance:
    def test_the_worsened_task_escalates_and_records_the_second_nurse(
        self, world, draft_window_and_reached_callback
    ):
        """PRD §3.8: "All three are recorded, along with `verified_by_nurse_id` as
        the acting nurse's identifier and `verified_at` as the current
        logical-clock instant, and the task's `version` increases by one."

        Design: Difficulty/transitive_cascade/worsened_callback_escalates_variance_and_blocks_the_practices_draft_coverage_window
        """
        _, _, _, task = draft_window_and_reached_callback

        verified = world.verify_callback(
            task["id"], "nurse_c", patient_condition="WORSENED", advice_followed=False
        )

        assert verified["status"] == "ESCALATED"
        assert verified["patient_condition"] == "WORSENED"
        assert verified["advice_followed"] is False
        assert verified["verified_by_nurse_id"] == world.nurse_id("nurse_c")
        assert_instant(verified["verified_at"], "2026-08-03T14:30:00Z", "verified_at")

    def test_the_audit_dimension_escalates_while_the_advice_stays_authorized(
        self, world, draft_window_and_reached_callback
    ):
        """PRD §2.10: "Two independent lifecycles live on the same `Disposition` row
        and never interfere."

        Design: Difficulty/transitive_cascade/worsened_callback_escalates_variance_and_blocks_the_practices_draft_coverage_window
        """
        _, _, disposition, task = draft_window_and_reached_callback

        world.verify_callback(
            task["id"], "nurse_c", patient_condition="WORSENED", advice_followed=False
        )

        after = world.disposition(disposition["id"])
        assert after["audit_status"] == "VARIANCE_ESCALATED"
        assert after["advice_status"] == "AUTHORIZED"

    def test_the_practice_counters_move_in_the_cascade(
        self, world, draft_window_and_reached_callback
    ):
        """PRD §3.8: "because that disposition entered variance escalation, the
        practice's `open_variance_count` increases by one; because
        `open_variance_count` reached the practice's `variance_review_threshold`,
        the practice's `compliance_posture` becomes `UNDER_REVIEW`".

        Design: Difficulty/transitive_cascade/worsened_callback_escalates_variance_and_blocks_the_practices_draft_coverage_window
        """
        _, _, _, task = draft_window_and_reached_callback

        world.verify_callback(
            task["id"], "nurse_c", patient_condition="WORSENED", advice_followed=False
        )

        practice = world.practice()
        assert practice["open_variance_count"] == 1
        assert practice["compliance_posture"] == "UNDER_REVIEW"
        assert practice["escalated_callback_count"] == 1
        assert practice["open_callback_count"] == 0

    def test_the_bystander_draft_window_is_blocked_with_the_exact_suspend_reason(
        self, world, draft_window_and_reached_callback
    ):
        """PRD §3.8: "and because the posture became `UNDER_REVIEW`, every coverage
        window of that practice whose `status` is `DRAFT` flips to `BLOCKED` with
        `suspend_reason` set to `PRACTICE_UNDER_COMPLIANCE_REVIEW`."

        Design: Difficulty/transitive_cascade/worsened_callback_escalates_variance_and_blocks_the_practices_draft_coverage_window
        """
        window, _, _, task = draft_window_and_reached_callback
        assert window["status"] == "DRAFT"
        assert window["suspend_reason"] is None

        world.verify_callback(
            task["id"], "nurse_c", patient_condition="WORSENED", advice_followed=False
        )

        blocked = world.coverage_window(window["id"])
        assert blocked["status"] == "BLOCKED"
        assert blocked["suspend_reason"] == SUSPEND_REASON_COMPLIANCE_REVIEW
        assert blocked["version"] > window["version"], (
            "each cascade hop bumps the version of the row it touches"
        )

    def test_an_ed_now_escalation_leaves_the_high_risk_counter_at_zero(
        self, world, draft_window_and_reached_callback
    ):
        """PRD §2.9: "`Nurse.pending_high_risk_count` is the number of calls
        assigned to that nurse that require a warm transfer and whose `status` is
        `ASSIGNED`, `ASSESSING` or `DISPOSITIONED`."

        Design: Difficulty/transitive_cascade/worsened_callback_escalates_variance_and_blocks_the_practices_draft_coverage_window
        """
        _, _, _, task = draft_window_and_reached_callback

        world.verify_callback(
            task["id"], "nurse_c", patient_condition="WORSENED", advice_followed=False
        )

        assert_nurse_load(
            world.nurse("nurse_a"), active=1, high_risk=0, eligibility="ON_ROTATION"
        )
