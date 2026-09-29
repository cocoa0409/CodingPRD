"""Cascades where each link is caused by the link before it.

One quality-control ruling can end a reviewer's engagement and unwind every
other batch they hold, and one late conflicts hit can withdraw paper, close a
platform session and reverse an outstanding commitment.
"""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers.assertions import (
    assert_ledger_sums_to,
    assert_money,
    assert_rate_4dp,
    assert_scorecard_events,
    assert_status,
)
from test_helpers.fixtures import REVIEWER_CLEO
from test_helpers.test_users import ENGAGEMENT_MANAGER, QC_LEAD, STAFFING_COORDINATOR


class TestQcFailureCascadesIntoRemovalAndVoidSweep:
    """A failed sample carrying privilege errors costs two strikes at once."""

    def _reviewer_on_the_brink(self, staffed_matter):
        """One pace strike already banked, one batch sampled, another committed."""
        ladder = staffed_matter["ladder"]
        ada_id = staffed_matter["ada_id"]

        first_batch = ladder.carve_batch(400)
        first = ladder.assign(
            first_batch["id"], ada_id, "FIRST_PASS", first_batch["version"]
        )
        ladder.start(first["id"], ada_id)
        # 400 documents in 600 minutes is 40.00 an hour, under the 55 floor.
        ladder.progress(first["id"], ada_id, 400, 600)
        ladder.submit(first["id"], ada_id)

        second_batch = ladder.carve_batch(200)
        second = ladder.assign(
            second_batch["id"], ada_id, "FIRST_PASS", second_batch["version"]
        )

        cleo = ladder.source_reviewer(REVIEWER_CLEO)
        sample = ladder.draw_sample(first_batch["id"], cleo["id"])
        return {
            "ladder": ladder,
            "ada_id": ada_id,
            "matter_id": staffed_matter["matter_id"],
            "first_batch_id": first_batch["id"],
            "first_assignment_id": first["id"],
            "second_batch_id": second_batch["id"],
            "second_assignment_id": second["id"],
            "sample_id": sample["id"],
        }

    def test_a_failed_sample_with_privilege_errors_appends_both_strike_events(
        self, staffed_matter
    ):
        """PRD §3.8: "Second, when `privilege_error_count` is greater than 0, a further
        scorecard event of type `PRIVILEGE_MISS` with `strike_delta` of +1 is appended
        for that same reviewer — so a failed sample containing privilege errors costs
        two strikes at once, not one."

        Three errors over forty sampled documents fails the batch, and the privilege
        error costs a second strike on top of the quality failure.

        Design: Difficulty/transitive_cascade/qc_failure_to_strike_to_removal_to_void_sweep
        """
        state = self._reviewer_on_the_brink(staffed_matter)
        ladder = state["ladder"]

        validated = ladder.validate_sample(state["sample_id"], 2, 1)
        assert validated["outcome"] == "FAILED"
        assert_rate_4dp(validated["discrepancy_rate"], 0.0750, "discrepancy_rate")
        assert_status(ladder.read_batch(state["first_batch_id"]), "QC_FAILED")

        events, _ = validate_paginated(
            ladder.api.list_scorecard_events(state["ada_id"], QC_LEAD, limit=100)
        )
        assert_scorecard_events(
            events,
            [
                ("PACE_SHORTFALL", 1),
                ("QC_FAILURE", 1),
                ("PRIVILEGE_MISS", 1),
                ("REMOVAL", 0),
            ],
        )

    def test_the_third_strike_removes_the_reviewer_and_sweeps_only_unbilled_work(
        self, staffed_matter
    ):
        """PRD §3.3: "When removal fires, the reviewer moves to `REMOVED` from either
        `ENGAGED` or `CLEARED`, and the following cascade runs in order: a scorecard
        event of type `REMOVAL` with `strike_delta` 0 is appended; `removed_at` is
        stamped from the logical clock; every assignment of this reviewer whose status
        is `ASSIGNED`, `IN_PROGRESS` or `REOPENED` becomes `VOIDED` with `void_reason`
        `REVIEWER_REMOVED`, processed in assignment `created_at` ascending order; each
        of those voided assignments appends a reversal ledger row of the negative of its
        `committed_amount_cents`, but only where its `billable_amount_cents` is still 0,
        since an assignment that has already billed keeps its actual row and is not
        reversed a second time; each batch of those voided assignments whose status is
        `ASSIGNED` or `IN_PROGRESS` returns to `CREATED`, while a batch already in
        `SECOND_LEVEL`, `QC_SAMPLING` or `QC_FAILED` keeps its status; and finally, for
        every affected matter, `committed_spend_cents` and `staffed_reviewer_count` are
        recomputed, with a matter in `IN_REVIEW` that has fallen below
        `min_staffed_reviewers` reverting to `STAFFING`."

        Removal voids every live assignment, but only the assignment that had not yet
        billed receives a reversal row.

        Design: Difficulty/transitive_cascade/qc_failure_to_strike_to_removal_to_void_sweep
        """
        state = self._reviewer_on_the_brink(staffed_matter)
        ladder = state["ladder"]

        ladder.validate_sample(state["sample_id"], 2, 1)

        reviewer = ladder.read_reviewer(state["ada_id"])
        assert reviewer["scorecard_strikes"] == 3
        assert_status(reviewer, "REMOVED", "engagement_status")
        assert reviewer["removed_at"] is not None
        # Strikes alone drove the removal. PRD §3.3 defines the accuracy sample set
        # as "every quality-control sample whose `outcome` is `PASSED` or `FAILED`
        # and whose batch carries a first-pass assignment belonging to this reviewer
        # in any status other than `VOIDED`" — the removal cascade has just voided
        # the only such assignment, so no sample qualifies any more and the recomputed
        # figure is the no-qualifying-samples value: "With no qualifying samples at
        # all, both variants return exactly 1.0000."
        assert_rate_4dp(reviewer["accuracy_score"], 1.0000, "accuracy_score")

        billed = ladder.read_assignment(state["first_assignment_id"])
        assert_status(billed, "VOIDED")
        assert billed["void_reason"] == "REVIEWER_REMOVED"
        assert_money(billed["billable_amount_cents"], 85200, "billable_amount_cents")

        unbilled = ladder.read_assignment(state["second_assignment_id"])
        assert_status(unbilled, "VOIDED")
        assert unbilled["void_reason"] == "REVIEWER_REMOVED"

        billed_rows, _ = validate_paginated(
            ladder.api.list_assignment_budget_ledger(
                state["first_assignment_id"], ENGAGEMENT_MANAGER, limit=100
            )
        )
        assert sorted(row["entry_type"] for row in billed_rows) == [
            "ACTUAL_PER_DOCUMENT",
            "COMMITMENT",
            "REVERSAL",
        ]

        unbilled_rows, _ = validate_paginated(
            ladder.api.list_assignment_budget_ledger(
                state["second_assignment_id"], ENGAGEMENT_MANAGER, limit=100
            )
        )
        assert [
            (row["entry_type"], row["amount_cents"]) for row in unbilled_rows
        ] == [("COMMITMENT", 42600), ("REVERSAL", -42600)]

        matter_rows, _ = validate_paginated(
            ladder.api.list_matter_budget_ledger(
                state["matter_id"], ENGAGEMENT_MANAGER, limit=100
            )
        )
        assert_ledger_sums_to(matter_rows, 85200)

        assert_status(ladder.read_batch(state["second_batch_id"]), "CREATED")
        assert_status(ladder.read_batch(state["first_batch_id"]), "QC_FAILED")

        matter = validate_success(
            ladder.api.get_matter(state["matter_id"], ENGAGEMENT_MANAGER)
        )
        assert matter["staffed_reviewer_count"] == 0
        assert_status(matter, "STAFFING")
        assert_money(matter["committed_spend_cents"], 85200, "committed_spend_cents")


class TestBlockedRescreeningCascade:
    """A late conflicts hit withdraws paper, access and money in that order."""

    def test_blocking_a_cleared_screening_revokes_the_agreement_and_the_session(
        self, assigned_batch
    ):
        """PRD §3.4: "Caused by the block: every confidentiality agreement for that
        reviewer-and-matter pair whose status is `PENDING` or `EXECUTED` becomes
        `REVOKED` with `revocation_reason` set to `CONFLICTS_BLOCKED`, each such
        agreement's `version` incrementing."

        The agreement is withdrawn because of the block, and the platform session is
        closed because of the withdrawal.

        Design: Difficulty/transitive_cascade/blocked_rescreening_to_agreement_to_session_to_void
        """
        ladder = assigned_batch["ladder"]
        ada = assigned_batch["ada"]

        blocked = ladder.decide_screening(
            ada["screening_id"],
            "BLOCKED",
            "late-declared adverse party surfaced in re-screening",
        )
        assert_status(blocked, "BLOCKED")
        assert blocked["screened_at"] is not None

        agreement = validate_success(
            ladder.api.get_agreement(ada["agreement_id"], STAFFING_COORDINATOR)
        )
        assert_status(agreement, "REVOKED")
        assert agreement["revocation_reason"] == "CONFLICTS_BLOCKED"

        session = validate_success(
            ladder.api.get_session(
                assigned_batch["ada_session_id"], STAFFING_COORDINATOR
            )
        )
        assert_status(session, "REVOKED")
        assert session["closed_at"] is not None

        matter = validate_success(
            ladder.api.get_matter(assigned_batch["matter_id"], ENGAGEMENT_MANAGER)
        )
        assert matter["staffed_reviewer_count"] == 0
        assert_status(matter, "STAFFING")

    def test_the_revocation_voids_the_assignment_and_reverses_its_commitment(
        self, assigned_batch
    ):
        """PRD §3.4: "Each such void appends a reversal ledger row of the negative of
        that assignment's `committed_amount_cents`, but only where its
        `billable_amount_cents` is still 0 — an assignment that already billed keeps its
        actual row and is not reversed twice."

        The outstanding commitment is reversed rather than deleted, the batch becomes
        re-staffable, and the reviewer merely falls back to sourced.

        Design: Difficulty/transitive_cascade/blocked_rescreening_to_agreement_to_session_to_void
        """
        ladder = assigned_batch["ladder"]
        ada = assigned_batch["ada"]

        ladder.decide_screening(
            ada["screening_id"],
            "BLOCKED",
            "late-declared adverse party surfaced in re-screening",
        )

        assignment = ladder.read_assignment(assigned_batch["assignment_id"])
        assert_status(assignment, "VOIDED")
        assert assignment["void_reason"] == "CONFLICTS_BLOCKED"

        rows, _ = validate_paginated(
            ladder.api.list_matter_budget_ledger(
                assigned_batch["matter_id"], ENGAGEMENT_MANAGER, limit=100
            )
        )
        assert [(row["entry_type"], row["amount_cents"]) for row in rows] == [
            ("COMMITMENT", 85200),
            ("REVERSAL", -85200),
        ]
        assert_ledger_sums_to(rows, 0)

        matter = validate_success(
            ladder.api.get_matter(assigned_batch["matter_id"], ENGAGEMENT_MANAGER)
        )
        assert_money(matter["committed_spend_cents"], 0, "committed_spend_cents")
        assert_status(ladder.read_batch(assigned_batch["batch_id"]), "CREATED")

        reviewer = ladder.read_reviewer(assigned_batch["ada_id"])
        assert_status(reviewer, "SOURCED", "engagement_status")
        assert reviewer["scorecard_strikes"] == 0
