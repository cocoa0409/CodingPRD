"""Two readings of the same data that must not be allowed to collapse together.

The spend projection prices identical facts twice — forward at the contract
rate over uncoded work, and backward as a replay of the ledger at the
reviewer's own effective rate — and the scorecard pools quality-control samples
two different ways over one sample set.
"""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers.assertions import (
    assert_money,
    assert_rate_4dp,
    assert_status,
    contract_rate_cents,
    effective_per_document_cents,
)
from test_helpers.fixtures import REVIEWER_CLEO
from test_helpers.test_users import ENGAGEMENT_MANAGER, QC_LEAD, STAFFING_COORDINATOR


class TestSpendBasisDivergence:
    """The forward and backward spend bases are both always returned."""

    def test_remaining_work_and_ledger_replay_bases_diverge_on_identical_facts(
        self, staffed_matter
    ):
        """PRD §3.9: "`variance_cents` is `remaining_work_basis_cents` minus
        `ledger_replay_basis_cents`, and it is expected to be non-zero: the divergence
        is structural, since one basis prices remaining work at the contract rate while
        the other prices committed work at premium rates."

        Both bases are computed and they disagree, because one prices uncoded documents
        at the contract rate while the other replays the committed ledger at the
        reviewer's effective rate.

        Design: Difficulty/dual_variant_calc/spend_projection_remaining_work_vs_ledger_replay
        """
        ladder = staffed_matter["ladder"]
        matter_id = staffed_matter["matter_id"]
        ada_id = staffed_matter["ada_id"]

        first_batch = ladder.carve_batch(400)
        assignment = ladder.assign(
            first_batch["id"], ada_id, "FIRST_PASS", first_batch["version"]
        )
        ladder.start(assignment["id"], ada_id)
        ladder.progress(assignment["id"], ada_id, 250, 270)
        ladder.carve_batch(200)

        projection = validate_success(
            ladder.api.get_spend_projection(matter_id, ENGAGEMENT_MANAGER)
        )

        # The contract rate excludes the reviewer's language premium; the rate
        # actually pinned on the assignment includes it.
        contract_rate = contract_rate_cents(150, "COMPLEX")
        pinned_rate = effective_per_document_cents(150, "COMPLEX", 1, "FIRST_PASS")
        assert contract_rate == 203
        assert pinned_rate == 213

        assert projection["basis_applied"] == "REMAINING_WORK_BASIS"
        assert_money(
            projection["remaining_work_basis_cents"],
            contract_rate * (150 + 200 + 0),
            "remaining_work_basis_cents",
        )
        assert_money(
            projection["ledger_replay_basis_cents"],
            pinned_rate * 400,
            "ledger_replay_basis_cents",
        )
        assert_money(projection["variance_cents"], 71050 - 85200, "variance_cents")

    def test_no_submitted_assignment_leaves_the_invoice_empty_and_headroom_forward_looking(
        self, staffed_matter
    ):
        """PRD §3.9: "Headroom is therefore measured against the applied basis, not
        against the invoice total, and it can be negative when the applied basis has run
        past the cap."

        With nothing submitted the waterfall is all zeros, while headroom is still
        measured against the forward-looking basis the status selects.

        Design: Difficulty/dual_variant_calc/spend_projection_remaining_work_vs_ledger_replay
        """
        ladder = staffed_matter["ladder"]
        matter_id = staffed_matter["matter_id"]
        ada_id = staffed_matter["ada_id"]

        first_batch = ladder.carve_batch(400)
        assignment = ladder.assign(
            first_batch["id"], ada_id, "FIRST_PASS", first_batch["version"]
        )
        ladder.start(assignment["id"], ada_id)
        ladder.progress(assignment["id"], ada_id, 250, 270)
        ladder.carve_batch(200)

        projection = validate_success(
            ladder.api.get_spend_projection(matter_id, ENGAGEMENT_MANAGER)
        )

        assert_money(projection["gross_billable_cents"], 0, "gross_billable_cents")
        assert_money(projection["invoice_total_cents"], 0, "invoice_total_cents")
        assert_money(
            projection["budget_headroom_cents"],
            600000 - 71050,
            "budget_headroom_cents",
        )

        matter = validate_success(ladder.api.get_matter(matter_id, ENGAGEMENT_MANAGER))
        assert_money(matter["committed_spend_cents"], 85200, "committed_spend_cents")


class TestAccuracyWeightingVariants:
    """Pooling documents and averaging batches give different accuracies."""

    def _two_sampled_batches(self, staffed_matter):
        ladder = staffed_matter["ladder"]
        ada_id = staffed_matter["ada_id"]

        first_batch = ladder.carve_batch(400)
        first = ladder.assign(
            first_batch["id"], ada_id, "FIRST_PASS", first_batch["version"]
        )
        ladder.start(first["id"], ada_id)
        ladder.progress(first["id"], ada_id, 400, 420)
        ladder.submit(first["id"], ada_id)

        cleo = ladder.source_reviewer(REVIEWER_CLEO)
        first_sample = ladder.draw_sample(first_batch["id"], cleo["id"])
        ladder.validate_sample(first_sample["id"], 1, 0)

        second_batch = ladder.carve_batch(200)
        second = ladder.assign(
            second_batch["id"], ada_id, "FIRST_PASS", second_batch["version"]
        )
        ladder.start(second["id"], ada_id)
        ladder.progress(second["id"], ada_id, 200, 210)
        ladder.submit(second["id"], ada_id)

        second_sample = ladder.draw_sample(second_batch["id"], cleo["id"])
        ladder.validate_sample(second_sample["id"], 0, 0)
        return {
            "ladder": ladder,
            "ada_id": ada_id,
            "first_sample_id": first_sample["id"],
            "second_sample_id": second_sample["id"],
        }

    def test_sample_weighted_pools_documents_while_assignment_mean_averages_batches(
        self, staffed_matter
    ):
        """PRD §3.3: "The `ASSIGNMENT_MEAN` variant gives every sampled batch equal
        weight regardless of size: for each sample compute 1 minus its combined error
        count divided by its own `sampled_document_count`, then take the unweighted
        arithmetic mean of those per-sample figures and round half up to four decimal
        places."

        One error over sixty pooled documents is not the mean of one error over forty
        and none over twenty.

        Design: Difficulty/dual_variant_calc/reviewer_accuracy_sample_weighted_vs_assignment_mean
        """
        state = self._two_sampled_batches(staffed_matter)
        ladder = state["ladder"]
        ada_id = state["ada_id"]

        first_sample = validate_success(
            ladder.api.get_qc_sample(state["first_sample_id"], QC_LEAD)
        )
        second_sample = validate_success(
            ladder.api.get_qc_sample(state["second_sample_id"], QC_LEAD)
        )
        assert first_sample["sampled_document_count"] == 40
        assert second_sample["sampled_document_count"] == 20

        pooled = validate_success(
            ladder.api.get_scorecard(ada_id, STAFFING_COORDINATOR)
        )
        assert pooled["weighting_applied"] == "SAMPLE_WEIGHTED"
        assert_rate_4dp(pooled["accuracy_score"], 0.9833, "accuracy_score")
        assert pooled["sampled_document_count"] == 60
        assert pooled["total_error_count"] == 1

        averaged = validate_success(
            ladder.api.get_scorecard(
                ada_id, STAFFING_COORDINATOR, weighting="ASSIGNMENT_MEAN"
            )
        )
        assert averaged["weighting_applied"] == "ASSIGNMENT_MEAN"
        assert_rate_4dp(averaged["accuracy_score"], 0.9875, "accuracy_score")

    def test_stored_accuracy_uses_the_pooled_variant_and_the_clean_credit_floors_at_zero(
        self, staffed_matter
    ):
        """PRD §3.3: "The reviewer's stored `accuracy_score` and the auto-assignment
        selector **always** use `SAMPLE_WEIGHTED`; the scorecard read accepts an
        optional `weighting` of `SAMPLE_WEIGHTED` or `ASSIGNMENT_MEAN`, defaults to
        `SAMPLE_WEIGHTED`, and always names the variant it used in the response's
        `weighting_applied` field."

        The reviewer row always carries the pooled figure, and the clean second sample's
        credit cannot drive the strike total below zero.

        Design: Difficulty/dual_variant_calc/reviewer_accuracy_sample_weighted_vs_assignment_mean
        """
        state = self._two_sampled_batches(staffed_matter)
        ladder = state["ladder"]

        reviewer = validate_success(
            ladder.api.get_reviewer(state["ada_id"], STAFFING_COORDINATOR)
        )
        assert_rate_4dp(reviewer["accuracy_score"], 0.9833, "accuracy_score")
        assert reviewer["scorecard_strikes"] == 0

        events, _ = validate_paginated(
            ladder.api.list_scorecard_events(
                state["ada_id"], STAFFING_COORDINATOR, limit=100
            )
        )
        credits = [row for row in events if row["event_type"] == "CLEARED_STRIKE"]
        assert len(credits) == 1
        assert credits[0]["strike_delta"] == -1
        assert_status(reviewer, "ENGAGED", "engagement_status")
