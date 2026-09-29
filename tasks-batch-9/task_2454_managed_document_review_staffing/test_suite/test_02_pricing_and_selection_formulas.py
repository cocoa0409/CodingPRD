"""Formulas whose intermediate ordering changes the answer.

Each of these three computations reaches a different result if a step is
reordered: rounding the rate before rather than after multiplication, selecting
the discount band from the provisional total rather than the gross, and walking
the tie-break keys in the documented sequence.
"""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers.assertions import (
    assert_ledger_movements,
    assert_money,
    assert_pace_2dp,
    assert_status,
    effective_per_document_cents,
    invoice_waterfall,
    selector_score,
)
from test_helpers.factories import auto_assign_payload
from test_helpers.test_users import (
    ENGAGEMENT_MANAGER,
    STAFFING_COORDINATOR,
)


class TestPerDocumentRateRoundedBeforeMultiplication:
    """The rate is rounded to whole cents first and multiplied second."""

    def test_rate_rounds_to_whole_cents_before_the_document_count_multiplies_it(
        self, started_assignment
    ):
        """PRD §3.6: "**Round that product half up to a whole number of cents first**,
        and store it as `effective_per_document_cents` — the rounding happens on the
        *rate*, before any multiplication by a document count."

        Rounding the rate first yields 213 a document and 85200 in total; rounding the
        product instead would yield 85050.

        Design: Difficulty/combinatorial_formula/per_document_rate_rounded_before_multiplication_mode_b
        """
        ladder = started_assignment["ladder"]
        assignment_id = started_assignment["assignment_id"]
        ada_id = started_assignment["ada_id"]

        ladder.progress(assignment_id, ada_id, 400, 420)
        submitted = validate_success(
            ladder.api.submit_assignment(assignment_id, started_assignment["ada_headers"])
        )

        assert_money(
            submitted["effective_per_document_cents"],
            effective_per_document_cents(150, "COMPLEX", 1, "FIRST_PASS"),
            "effective_per_document_cents",
        )
        assert submitted["effective_per_document_cents"] == 213
        assert_money(submitted["billable_amount_cents"], 85200, "billable_amount_cents")
        assert submitted["billable_amount_cents"] != 85050
        assert_money(
            submitted["committed_amount_cents"], 85200, "committed_amount_cents"
        )
        assert_pace_2dp(submitted["pace_dph"], 57.14)

    def test_one_commitment_one_reversal_and_one_actual_settle_the_assignment(
        self, started_assignment
    ):
        """PRD §3.7: "The first submit then appends the actual ledger row —
        `ACTUAL_PER_DOCUMENT` or `ACTUAL_HOURLY` according to the matter's
        `pricing_model` — appends the matching `REVERSAL` of this assignment's earlier
        `COMMITMENT`, sets `billable_amount_cents`, and recomputes the matter's
        `committed_spend_cents`."

        A submit at or above the pace floor writes three ledger rows and no pace strike,
        and the batch skips straight to sampling.

        Design: Difficulty/combinatorial_formula/per_document_rate_rounded_before_multiplication_mode_b
        """
        ladder = started_assignment["ladder"]
        assignment_id = started_assignment["assignment_id"]
        ada_id = started_assignment["ada_id"]

        ladder.progress(assignment_id, ada_id, 400, 420)
        ladder.submit(assignment_id, ada_id)

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
            ladder.api.get_matter(started_assignment["matter_id"], ENGAGEMENT_MANAGER)
        )
        assert_money(matter["committed_spend_cents"], 85200, "committed_spend_cents")

        batch = ladder.read_batch(started_assignment["batch_id"])
        assert_status(batch, "QC_SAMPLING")

        events, _ = validate_paginated(
            ladder.api.list_scorecard_events(ada_id, STAFFING_COORDINATOR, limit=100)
        )
        assert events == []


class TestInvoiceWaterfallBandSelectedAfterSurcharge:
    """The discount band is chosen from the provisional total, once."""

    def _two_submitted_batches(self, staffed_matter):
        ladder = staffed_matter["ladder"]
        ada_id = staffed_matter["ada_id"]

        first_batch = ladder.carve_batch(400)
        first = ladder.assign(
            first_batch["id"], ada_id, "FIRST_PASS", first_batch["version"]
        )
        ladder.start(first["id"], ada_id)
        ladder.progress(first["id"], ada_id, 400, 420)
        ladder.submit(first["id"], ada_id)

        second_batch = ladder.carve_batch(64)
        second = ladder.assign(
            second_batch["id"], ada_id, "FIRST_PASS", second_batch["version"]
        )
        ladder.start(second["id"], ada_id)
        ladder.progress(second["id"], ada_id, 64, 60)
        ladder.submit(second["id"], ada_id)
        return ladder

    def test_a_gross_below_the_band_floor_still_earns_the_discount_after_the_surcharge(
        self, staffed_matter
    ):
        """PRD §3.9: "Step four: `volume_discount_pct` is selected from
        `provisional_total_cents` — zero for a provisional total below 100000 cents,
        three hundredths for a provisional total from 100000 through 249999 cents
        inclusive, and six hundredths for a provisional total of 250000 cents or more —
        then `volume_discount_cents` is `provisional_total_cents` multiplied by
        `volume_discount_pct` rounded half up to whole cents, and `invoice_total_cents`
        is `provisional_total_cents` minus `volume_discount_cents`."

        A gross of 98832 sits below the first band floor, but the quality surcharge
        lifts the provisional total over it, so the band is 0.03.

        Design: Difficulty/combinatorial_formula/invoice_waterfall_band_selected_after_surcharge_mode_c
        """
        ladder = self._two_submitted_batches(staffed_matter)
        projection = validate_success(
            ladder.api.get_spend_projection(
                staffed_matter["matter_id"],
                ENGAGEMENT_MANAGER,
                basis="LEDGER_REPLAY_BASIS",
            )
        )

        expected = invoice_waterfall(98832, 0.10)
        assert expected["provisional_total_cents"] == 100809

        assert_money(projection["gross_billable_cents"], 98832, "gross_billable_cents")
        assert_money(projection["qc_surcharge_cents"], 1977, "qc_surcharge_cents")
        assert_money(
            projection["provisional_total_cents"], 100809, "provisional_total_cents"
        )
        assert projection["volume_discount_pct"] == 0.03
        assert_money(
            projection["volume_discount_cents"], 3024, "volume_discount_cents"
        )
        assert_money(projection["invoice_total_cents"], 97785, "invoice_total_cents")
        assert projection["invoice_total_cents"] != 100809

    def test_the_replay_basis_is_applied_when_asked_for_and_both_bases_are_returned(
        self, staffed_matter
    ):
        """PRD §3.9: "An explicit parameter always wins over the status-derived default,
        and the response's `basis_applied` field always names the variant that was
        used."

        An explicit basis wins, and the unselected basis is still computed so the two
        can be compared.

        Design: Difficulty/combinatorial_formula/invoice_waterfall_band_selected_after_surcharge_mode_c
        """
        ladder = self._two_submitted_batches(staffed_matter)
        projection = validate_success(
            ladder.api.get_spend_projection(
                staffed_matter["matter_id"],
                ENGAGEMENT_MANAGER,
                basis="LEDGER_REPLAY_BASIS",
            )
        )

        assert projection["basis_applied"] == "LEDGER_REPLAY_BASIS"
        assert_money(
            projection["ledger_replay_basis_cents"],
            98832,
            "ledger_replay_basis_cents",
        )
        assert_money(
            projection["remaining_work_basis_cents"],
            203 * 136,
            "remaining_work_basis_cents",
        )
        assert_money(projection["variance_cents"], 27608 - 98832, "variance_cents")


class TestAutoAssignTieBreakChain:
    """Score, then headroom, then hourly cost, then creation order."""

    def test_the_cheaper_reviewer_wins_once_score_and_headroom_have_tied(
        self, tie_break_pool
    ):
        """PRD §3.6: "Ties are broken by capacity headroom descending, where headroom is
        `max_concurrent_batches` minus `active_assignment_count`; then by
        `hourly_cost_cents` ascending, so the cheaper reviewer wins an otherwise dead
        heat; then by the reviewer's `created_at` ascending."

        Two reviewers identical on every scored dimension are separated by the third key
        in the chain, the provider's own hourly cost.

        Design: Difficulty/combinatorial_formula/auto_assign_tie_break_chain_mode_a
        """
        ladder = tie_break_pool["ladder"]
        batch_id = tie_break_pool["batch_id"]

        # Both candidates score 0.7000: full accuracy, no pace history, both
        # required languages matched and the single subject tag matched.
        assert selector_score(1.0, 0.00, 55, 2, 2, 1, 1, 0) == 0.7000

        fresh = validate_success(ladder.api.get_batch(batch_id, STAFFING_COORDINATOR))
        chosen = validate_success(
            ladder.api.auto_assign(
                batch_id,
                auto_assign_payload(fresh["version"], "FIRST_PASS"),
                STAFFING_COORDINATOR,
            ),
            expected_status=201,
        )

        assert chosen["reviewer_id"] == tie_break_pool["ada_id"]
        assert chosen["reviewer_id"] != tie_break_pool["dana_id"]
        assert_money(
            chosen["effective_per_document_cents"], 213, "effective_per_document_cents"
        )
        assert_money(chosen["committed_amount_cents"], 85200, "committed_amount_cents")

    def test_only_the_winner_is_engaged_and_only_one_assignment_is_created(
        self, tie_break_pool
    ):
        """PRD §3.6: "The winner is then assigned exactly as if they had been named,
        with the identical commitment, ledger, batch and reviewer side effects, the
        identical second-level separation rule, and the identical budget ceiling as the
        final check."

        Losing the tie-break leaves a candidate exactly where they were.

        Design: Difficulty/combinatorial_formula/auto_assign_tie_break_chain_mode_a
        """
        ladder = tie_break_pool["ladder"]
        batch_id = tie_break_pool["batch_id"]

        fresh = validate_success(ladder.api.get_batch(batch_id, STAFFING_COORDINATOR))
        validate_success(
            ladder.api.auto_assign(
                batch_id,
                auto_assign_payload(fresh["version"], "FIRST_PASS"),
                STAFFING_COORDINATOR,
            ),
            expected_status=201,
        )

        winner = ladder.read_reviewer(tie_break_pool["ada_id"])
        loser = ladder.read_reviewer(tie_break_pool["dana_id"])
        assert_status(winner, "ENGAGED", "engagement_status")
        assert_status(loser, "CLEARED", "engagement_status")

        assignments, _ = validate_paginated(
            ladder.api.list_assignments(STAFFING_COORDINATOR, batch_id=batch_id)
        )
        assert len(assignments) == 1
        assert_status(ladder.read_batch(batch_id), "ASSIGNED")
