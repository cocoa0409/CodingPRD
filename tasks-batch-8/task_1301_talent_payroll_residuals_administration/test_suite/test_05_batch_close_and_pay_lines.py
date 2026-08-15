"""Pay batch close: sweep, per-line calculation, garnishment waterfall, recall."""
from test_helpers import (
    ADMIN,
    CLERK,
    SUPERVISOR,
    ApiErrorId,
    assert_batch_totals_equal_line_sums,
    assert_pay_batch,
    assert_pay_line,
    assert_payline_net_identity,
    create_active_engagement,
    create_approved_timecard,
    create_garnishment,
    create_open_batch,
    create_performer,
    get_pay_batch,
    get_success_data,
    get_timecard,
    list_pay_lines,
    setup_closed_batch_with_tca,
    setup_standard,
    setup_with_approved_timecard,
    validate_error,
)


class TestGarnishmentWaterfallPerOrderRounding:
    """Standard line: gross 149375, tax 14938, disposable 134437, cap 33609."""

    def test_line_amounts_with_two_orders(self, api):
        """PRD §3.12: "For `TIMECARD` lines, `gross_cents` is the timecard's
        `day_gross_cents` plus the sum of `amount_cents` over that timecard's
        `CONFIRMED` penalty assessments."
        PRD §3.13: "`tax_cents` is the gross multiplied by that jurisdiction's
        `tax_pct`, rounded half-up to integer cents."
        PRD §3.14: "The line's `garnished_cents` is the line cap minus whatever
        remains after all orders have been considered."

        Design: Difficulty/combinatorial_formula/garnishment_waterfall_per_order_rounding
        """
        ctx = setup_closed_batch_with_tca(with_garnishments=True)
        assert len(ctx["lines"]) == 1
        line = ctx["lines"][0]
        assert_pay_line(line)
        assert line["gross_cents"] == 149375, "146875 day gross + 2500 penalty"
        assert line["tax_cents"] == 14938, "round_half_up(149375 x 0.10)"
        # O1 round_half_up(134437 x 0.20) = 26887; O2 fixed 5000.
        assert line["garnished_cents"] == 31887
        assert line["net_cents"] == 102550

    def test_per_order_rounding_precedes_allocation(self, api):
        """PRD §3.14: "For each order, the requested amount is the order's
        `fixed_amount_cents` if set, otherwise the line's disposable multiplied by
        the order's `pct_of_disposable`, rounded half-up to integer cents before
        any allocation." — 134437 x 0.20 = 26887.4 rounds to 26887, not 26888.
        PRD §3.15: "The employer-side PHW contribution on a pay line is the sum of
        three independently rounded components".

        Design: Difficulty/combinatorial_formula/garnishment_waterfall_per_order_rounding
        """
        ctx = setup_closed_batch_with_tca(with_garnishments=True)
        line = ctx["lines"][0]
        # Had O1 rounded to 26888, garnished would be 31888 and net 102549.
        assert line["garnished_cents"] == 31887
        # PHW: 8963 + 12697 + 1793, each component rounded half-up first.
        assert line["phw_cents"] == 23453
        assert_payline_net_identity(line)


class TestPaylineNetEvaluationOrder:
    def test_net_excludes_employer_phw(self, api):
        """PRD §3.13: "5. `phw_cents` is computed from gross (§3.15) but is
        employer-side and never subtracted from the line. 6. `net_cents` is
        `gross_cents` minus `tax_cents` minus `garnished_cents`".
        PRD §3.15: "PHW is never subtracted from `net_cents`; it is an employer
        obligation owed to the guild funds, tracked separately."

        Design: Difficulty/combinatorial_formula/payline_net_evaluation_order_pinned
        """
        ctx = setup_closed_batch_with_tca(with_garnishments=True)
        line = ctx["lines"][0]
        assert line["phw_cents"] == 23453
        assert line["net_cents"] == 102550, (
            "net == 149375 - 14938 - 31887; had PHW reduced net it would be 79097")
        assert line["net_cents"] == (
            line["gross_cents"] - line["tax_cents"] - line["garnished_cents"])

    def test_batch_totals_are_line_sums(self, api):
        """PRD §3.11: "The batch totals are then recomputed as sums over the
        created pay lines."

        Design: Difficulty/combinatorial_formula/payline_net_evaluation_order_pinned
        """
        ctx = setup_closed_batch_with_tca(with_garnishments=True)
        batch = ctx["bat"]
        assert_pay_batch(batch)
        assert batch["status"] == "CLOSED"
        assert_batch_totals_equal_line_sums(batch, ctx["lines"])
        assert batch["total_gross_cents"] == 149375
        assert batch["total_net_cents"] == 102550
        assert batch["total_garnished_cents"] == 31887
        assert batch["total_phw_cents"] == 23453


class TestGarnishmentCapExactCentClamp:
    """Two performers, each with an approved TC-A card (line gross 149375,
    disposable 134437, cap 33609). O1 takes 26887, leaving exactly 6722."""

    def _setup_two_performer_batch(self, api, second_fixed_amount):
        ctx = setup_with_approved_timecard()
        create_garnishment(ctx["perf"]["id"], creditor_name="County CSA",
                           order_type="CHILD_SUPPORT", priority_rank=1,
                           pct_of_disposable=0.20)
        create_garnishment(ctx["perf"]["id"], creditor_name="Exact Creditor",
                           order_type="CREDITOR_JUDGMENT", priority_rank=2,
                           fixed_amount_cents=second_fixed_amount)
        perf2 = create_performer(legal_name="Jordan Star")
        eng2 = create_active_engagement(ctx["prod"]["id"], ctx["agr"]["id"],
                                        perf2["id"])
        create_approved_timecard(eng2["id"])
        create_garnishment(perf2["id"], creditor_name="County CSA",
                           order_type="CHILD_SUPPORT", priority_rank=1,
                           pct_of_disposable=0.20)
        create_garnishment(perf2["id"], creditor_name="Overask Creditor",
                           order_type="CREDITOR_JUDGMENT", priority_rank=2,
                           fixed_amount_cents=second_fixed_amount + 1)
        batch = create_open_batch()
        get_success_data(api.close_pay_batch(batch["id"], CLERK))
        lines = list_pay_lines()
        line1 = next(l for l in lines
                     if l["engagement_id"] == ctx["eng"]["id"])
        line2 = next(l for l in lines if l["engagement_id"] == eng2["id"])
        return get_pay_batch(batch["id"]), line1, line2

    def test_request_exactly_at_remaining_cap_allocates_in_full(self, api):
        """PRD §3.14: "The allocated amount is the lesser of the requested amount
        and the remaining cap." A fixed request of exactly the remaining cap
        (6722) allocates in full, so the line garnishes exactly its cap.

        Design: Difficulty/boundary_precision_check/garnishment_cap_exact_cent_clamp
        """
        _batch, line1, _line2 = self._setup_two_performer_batch(api, 6722)
        assert line1["garnished_cents"] == 33609, (
            "26887 + 6722 lands exactly on the 25% disposable cap")
        assert line1["net_cents"] == 100828
        assert_payline_net_identity(line1)

    def test_request_one_cent_over_cap_clamps(self, api):
        """PRD §3.14: "total garnished on a single line never exceeds 25 percent
        of that line's disposable." A fixed request one cent above the remaining
        cap (6723) clamps to 6722, producing identical results.

        Design: Difficulty/boundary_precision_check/garnishment_cap_exact_cent_clamp
        """
        batch, line1, line2 = self._setup_two_performer_batch(api, 6722)
        assert line2["garnished_cents"] == 33609, "O2' clamped from 6723 to 6722"
        assert line2["net_cents"] == 100828
        assert batch["total_garnished_cents"] == 67218
        assert batch["total_gross_cents"] == 298750


class TestLoanOutVariant:
    def test_loan_out_line_paid_gross_no_withholding(self, api):
        """PRD §3.13: "For an engagement whose `payee_type` is `LOAN_OUT`,
        `tax_cents` is zero regardless of jurisdiction — loan-out corporations are
        paid gross."
        PRD §3.14: "Two exemptions apply: lines belonging to a `LOAN_OUT`
        engagement are exempt ... Exempt lines always carry `garnished_cents` = 0."
        PRD §3.13: "for a `LOAN_OUT` engagement, `net_cents` equals `gross_cents`
        by construction."
        PRD §3.15: "The employer-side PHW contribution on a pay line is the sum of
        three independently rounded components".

        Design: Corner/calculations/loan_out_line_paid_gross_no_withholding
        """
        ctx = setup_with_approved_timecard(
            payee_type="LOAN_OUT",
            loan_out_legal_name="Starlight Loans Inc",
            loan_out_tax_id="12-3456789")
        create_garnishment(ctx["perf"]["id"])  # ACTIVE order exists but is exempt
        batch = create_open_batch()
        get_success_data(api.close_pay_batch(batch["id"], CLERK))
        lines = list_pay_lines()
        assert len(lines) == 1
        line = lines[0]
        assert_pay_line(line)
        assert line["gross_cents"] == 149375
        assert line["tax_cents"] == 0, "loan-out corporations are paid gross"
        assert line["garnished_cents"] == 0, "loan-out lines are garnishment-exempt"
        assert line["net_cents"] == 149375, "net == gross for LOAN_OUT"
        assert line["phw_cents"] == 23453, (
            "PHW employer contributions still accrue on gross for loan-outs")


class TestBatchOpenUniqueness:
    def test_second_open_batch_rejected(self, api):
        """PRD §3.11: "At most one batch may be `OPEN` at a time; attempting to
        open a second is rejected with `ERR_OPEN_BATCH_EXISTS`."

        Design: Corner/validations/second_open_batch_rejected
        """
        create_open_batch()
        resp = api.create_pay_batch(
            {"period_label": "2026-W34", "cutoff_date": "2026-09-06"}, CLERK)
        validate_error(resp, ApiErrorId.ERR_OPEN_BATCH_EXISTS)


class TestBatchCloseEmptySweep:
    def test_close_with_empty_sweep_rejected(self, api):
        """PRD §3.11: "If the sweep set is empty, the close is rejected with
        `ERR_BATCH_EMPTY`."

        Design: Corner/validations/batch_close_empty_sweep_rejected
        """
        setup_standard()  # ACTIVE engagement, but nothing approved to sweep
        batch = create_open_batch()
        resp = api.close_pay_batch(batch["id"], CLERK)
        validate_error(resp, ApiErrorId.ERR_BATCH_EMPTY)
        assert get_pay_batch(batch["id"])["status"] == "OPEN"


class TestBatchCloseStateBeatsEmpty:
    def _setup_closed_batch(self, api):
        ctx = setup_with_approved_timecard()
        batch = create_open_batch()
        get_success_data(api.close_pay_batch(batch["id"], CLERK))
        return ctx, batch

    def test_second_close_reports_state_error_not_empty(self, api):
        """PRD §2.7: "When a request violates multiple rules, the rejection
        surfaces the highest-priority failure." — "4. State gates on the target
        resource: batch lifecycle (`ERR_BATCH_INVALID_STATE`)" precede
        "9. Business-fiscal rules (batch empty, grievance no-open-batch)".
        PRD §3.11: "Close against a batch not in `OPEN` status is rejected with
        `ERR_BATCH_INVALID_STATE`".

        Design: Difficulty/priority_pair_validation_conflict/batch_close_state_error_beats_empty_fiscal
        """
        _ctx, batch = self._setup_closed_batch(api)
        # The only timecard is already BATCHED, so the sweep set is now empty
        # too — yet the state gate (higher priority) must surface.
        resp = api.close_pay_batch(batch["id"], CLERK)
        validate_error(resp, ApiErrorId.ERR_BATCH_INVALID_STATE)

    def test_failed_second_close_leaves_batch_and_lines_intact(self, api):
        """PRD §3.11: "Close against a batch not in `OPEN` status is rejected with
        `ERR_BATCH_INVALID_STATE`". The rejected close mutates nothing: the batch
        stays CLOSED with its pay lines and totals intact.

        Design: Difficulty/priority_pair_validation_conflict/batch_close_state_error_beats_empty_fiscal
        """
        ctx, batch = self._setup_closed_batch(api)
        validate_error(api.close_pay_batch(batch["id"], CLERK),
                       ApiErrorId.ERR_BATCH_INVALID_STATE)
        batch_after = get_pay_batch(batch["id"])
        assert batch_after["status"] == "CLOSED"
        assert batch_after["total_gross_cents"] == 149375
        lines = list_pay_lines()
        assert len(lines) == 1
        assert lines[0]["pay_batch_id"] == batch["id"]
        assert get_timecard(ctx["tc"]["id"])["payment_status"] == "BATCHED"


class TestCloseRecallRecloseConservation:
    def test_close_then_recall_zeroes_everything(self, api):
        """PRD §3.11: "Recalling an `APPROVED` batch by a `PayrollSupervisor` is
        the compensating action: it transitions the batch back to `OPEN`, deletes
        every pay line of the batch, reverts each swept timecard from `BATCHED` to
        `UNBATCHED` (its `review_status` stays `APPROVED`), reverts each swept
        residual from `BATCHED` to `APPROVED`, resets all five batch totals to
        zero, and increments `version`."

        Design: Difficulty/compensating_invariant/batch_close_recall_reclose_totals_conserved
        """
        ctx = setup_with_approved_timecard()
        batch = create_open_batch()
        closed = get_success_data(api.close_pay_batch(batch["id"], CLERK))
        assert closed["total_gross_cents"] == 149375
        assert closed["total_tax_cents"] == 14938
        assert closed["total_garnished_cents"] == 0
        assert closed["total_phw_cents"] == 23453
        assert closed["total_net_cents"] == 134437
        assert_batch_totals_equal_line_sums(closed, list_pay_lines())

        get_success_data(api.approve_pay_batch(batch["id"], SUPERVISOR))
        recalled = get_success_data(api.recall_pay_batch(batch["id"], SUPERVISOR))
        assert recalled["status"] == "OPEN"
        for total in ("total_gross_cents", "total_tax_cents",
                      "total_garnished_cents", "total_phw_cents",
                      "total_net_cents"):
            assert recalled[total] == 0, f"{total} reset to zero by recall"
        assert list_pay_lines() == [], "recall deletes every pay line"
        tc_after = get_timecard(ctx["tc"]["id"])
        assert tc_after["payment_status"] == "UNBATCHED"
        assert tc_after["review_status"] == "APPROVED"

    def test_reclose_reproduces_identical_totals(self, api):
        """PRD §3.11: "The batch totals are then recomputed as sums over the
        created pay lines." After a close/recall/re-close cycle the recomputed
        totals are identical — close paired with its compensating action leaves
        zero drift.

        Design: Difficulty/compensating_invariant/batch_close_recall_reclose_totals_conserved
        """
        ctx = setup_with_approved_timecard()
        batch = create_open_batch()
        get_success_data(api.close_pay_batch(batch["id"], CLERK))
        get_success_data(api.approve_pay_batch(batch["id"], SUPERVISOR))
        get_success_data(api.recall_pay_batch(batch["id"], SUPERVISOR))
        reclosed = get_success_data(api.close_pay_batch(batch["id"], CLERK))
        assert reclosed["status"] == "CLOSED"
        assert reclosed["total_gross_cents"] == 149375
        assert reclosed["total_tax_cents"] == 14938
        assert reclosed["total_garnished_cents"] == 0
        assert reclosed["total_phw_cents"] == 23453
        assert reclosed["total_net_cents"] == 134437
        assert_batch_totals_equal_line_sums(reclosed, list_pay_lines())


class TestGarnishmentReleaseRestoresNetIdentity:
    def test_first_close_allocates_both_orders(self, api):
        """PRD §3.14: "The line's `garnished_cents` is the line cap minus whatever
        remains after all orders have been considered."
        PRD §3.13: "`net_cents` is `gross_cents` minus `tax_cents` minus
        `garnished_cents`".

        Design: Difficulty/compensating_invariant/garnishment_release_restores_net_identity
        """
        ctx = setup_closed_batch_with_tca(with_garnishments=True)
        line = ctx["lines"][0]
        assert line["garnished_cents"] == 31887
        assert line["net_cents"] == 102550
        assert_payline_net_identity(line)

    def test_release_between_closes_moves_net_by_released_allocation(self, api):
        """PRD §3.10: "A released order is excluded from all future batch
        waterfalls, though its historical `total_withheld_cents` remains on
        record."
        PRD §3.13: "`net_cents` is `gross_cents` minus `tax_cents` minus
        `garnished_cents`".

        Design: Difficulty/compensating_invariant/garnishment_release_restores_net_identity
        """
        ctx = setup_with_approved_timecard()
        create_garnishment(ctx["perf"]["id"], creditor_name="County CSA",
                           order_type="CHILD_SUPPORT", priority_rank=1,
                           pct_of_disposable=0.20)
        g2 = create_garnishment(ctx["perf"]["id"], creditor_name="Collections Inc",
                                order_type="CREDITOR_JUDGMENT", priority_rank=2,
                                fixed_amount_cents=5000)
        batch = create_open_batch()
        get_success_data(api.close_pay_batch(batch["id"], CLERK))
        line_before = list_pay_lines()[0]
        assert line_before["garnished_cents"] == 31887

        get_success_data(api.approve_pay_batch(batch["id"], SUPERVISOR))
        get_success_data(api.recall_pay_batch(batch["id"], SUPERVISOR))
        released = get_success_data(api.release_garnishment_order(g2["id"], ADMIN))
        assert released["status"] == "RELEASED"

        get_success_data(api.close_pay_batch(batch["id"], CLERK))
        line_after = list_pay_lines()[0]
        assert line_after["garnished_cents"] == 26887, "O1 only after O2 release"
        assert line_after["net_cents"] == 107550, (
            "net moved by exactly O2's released 5000-cent allocation")
        assert_payline_net_identity(line_after)

