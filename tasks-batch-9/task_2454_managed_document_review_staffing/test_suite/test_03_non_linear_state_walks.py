"""Loops that revisit a status without repeating its side effects.

A reopened assignment walks back through coding and submission without billing
twice, and a suspended matter walks back to review without undoing the session
revocations the suspension caused.
"""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers.assertions import (
    assert_ledger_movements,
    assert_money,
    assert_scorecard_events,
    assert_status,
)
from test_helpers.test_users import ENGAGEMENT_MANAGER, QC_LEAD, STAFFING_COORDINATOR


class TestReworkCycleIsNonBillable:
    """A reopened assignment can be recoded and resubmitted for free."""

    def test_restarting_a_reopened_assignment_walks_the_batch_back_to_sampling(
        self, failed_sample
    ):
        """PRD §3.8: "**Rework.** From `QC_FAILED` the reopened assignment is started
        again, carrying the batch `QC_FAILED → IN_PROGRESS`, and resubmitted, carrying
        it back to `QC_SAMPLING` where a fresh sample may be drawn."

        The reopened assignment returns to coding and its second submit puts the batch
        back into sampling without a second-level detour.

        Design: Difficulty/non_linear_state_machine/assignment_rework_cycle_is_non_billable
        """
        ladder = failed_sample["ladder"]
        assignment_id = failed_sample["assignment_id"]
        ada_id = failed_sample["ada_id"]
        batch_id = failed_sample["batch_id"]

        assert_status(ladder.read_assignment(assignment_id), "REOPENED")
        assert_status(ladder.read_batch(batch_id), "QC_FAILED")

        restarted = ladder.start(assignment_id, ada_id)
        assert_status(restarted, "IN_PROGRESS")
        assert_status(ladder.read_batch(batch_id), "IN_PROGRESS")

        resubmitted = ladder.submit(assignment_id, ada_id)
        assert_status(resubmitted, "SUBMITTED")
        assert_status(ladder.read_batch(batch_id), "QC_SAMPLING")

    def test_the_second_submit_neither_bills_again_nor_adds_a_strike(
        self, failed_sample
    ):
        """PRD §3.7: "When it is greater than 0, this is a rework resubmission and there
        is **no ledger movement at all** — no second actual row, no second reversal,
        nothing."

        Billing happens exactly once, so the rework submit writes no fourth ledger row
        and leaves the single quality-failure strike alone.

        Design: Difficulty/non_linear_state_machine/assignment_rework_cycle_is_non_billable
        """
        ladder = failed_sample["ladder"]
        assignment_id = failed_sample["assignment_id"]
        ada_id = failed_sample["ada_id"]

        ladder.start(assignment_id, ada_id)
        resubmitted = ladder.submit(assignment_id, ada_id)

        assert_money(
            resubmitted["billable_amount_cents"], 85200, "billable_amount_cents"
        )

        rows, _ = validate_paginated(
            ladder.api.list_assignment_budget_ledger(
                assignment_id, ENGAGEMENT_MANAGER, limit=100
            )
        )
        assert_ledger_movements(
            rows,
            [
                ("COMMITMENT", 85200),
                ("REVERSAL", -85200),
                ("ACTUAL_PER_DOCUMENT", 85200),
            ],
        )

        matter = validate_success(
            ladder.api.get_matter(failed_sample["matter_id"], ENGAGEMENT_MANAGER)
        )
        assert_money(matter["committed_spend_cents"], 85200, "committed_spend_cents")

        reviewer = ladder.read_reviewer(ada_id)
        assert reviewer["scorecard_strikes"] == 1

        events, _ = validate_paginated(
            ladder.api.list_scorecard_events(ada_id, QC_LEAD, limit=100)
        )
        assert_scorecard_events(events, [("QC_FAILURE", 1)])


class TestSuspensionRevertDoesNotRestoreSessions:
    """Resuming a matter is not an undo of the suspension's cascade."""

    def test_suspension_revokes_the_live_session_and_voids_nothing(
        self, assigned_batch
    ):
        """PRD §3.1: "Setting `suspended` to true moves a matter in `STAFFING`,
        `IN_REVIEW` or `QC_CLOSEOUT` to `SUSPENDED`, records the supplied
        `suspension_reason`, and revokes every secure-environment session of the matter
        whose status is `SCHEDULED` or `ACTIVE` — each such session moves to `REVOKED`
        with `closed_at` stamped from the logical clock — and increments the matter's
        `version`."

        The emergency brake closes the reviewer out of the platform while leaving the
        assignment and its commitment exactly where they were.

        Design: Difficulty/non_linear_state_machine/matter_suspension_revert_does_not_restore_sessions
        """
        ladder = assigned_batch["ladder"]
        matter_id = assigned_batch["matter_id"]

        suspended = ladder.suspend_matter("client instruction to pause review")
        assert_status(suspended, "SUSPENDED")
        assert suspended["suspension_reason"] == "client instruction to pause review"

        session = validate_success(
            ladder.api.get_session(
                assigned_batch["ada_session_id"], STAFFING_COORDINATOR
            )
        )
        assert_status(session, "REVOKED")
        assert session["closed_at"] is not None

        assert_status(ladder.read_assignment(assigned_batch["assignment_id"]), "ASSIGNED")
        matter = validate_success(ladder.api.get_matter(matter_id, ENGAGEMENT_MANAGER))
        assert matter["staffed_reviewer_count"] == 1
        assert_money(matter["committed_spend_cents"], 85200, "committed_spend_cents")

    def test_resuming_clears_the_reason_and_leaves_the_revoked_session_revoked(
        self, assigned_batch
    ):
        """PRD §3.1: "Revoked sessions are deliberately **not** restored on resume: the
        reviewer must schedule a fresh window."

        The matter walks back to review because staffing is intact, but the reviewer
        must schedule a fresh window.

        Design: Difficulty/non_linear_state_machine/matter_suspension_revert_does_not_restore_sessions
        """
        ladder = assigned_batch["ladder"]

        ladder.suspend_matter("client instruction to pause review")
        resumed = ladder.resume_matter()

        assert_status(resumed, "IN_REVIEW")
        assert resumed["suspension_reason"] is None

        session = validate_success(
            ladder.api.get_session(
                assigned_batch["ada_session_id"], STAFFING_COORDINATOR
            )
        )
        assert_status(session, "REVOKED")

        matter = validate_success(
            ladder.api.get_matter(assigned_batch["matter_id"], ENGAGEMENT_MANAGER)
        )
        assert matter["staffed_reviewer_count"] == 1
        assert_money(matter["committed_spend_cents"], 85200, "committed_spend_cents")
