"""Year-end true-up runs: computation variants, range boundaries, approval
gates, and the post cascade."""
from test_helpers import (
    ADMIN,
    ANALYST,
    MANAGER,
    TREASURY,
    ApiErrorId,
    approve_run,
    begin_closing,
    book_and_match,
    book_transaction,
    compute_run,
    create_active_agreement,
    create_computed_run,
    create_run,
    find_position,
    post_run,
    setup_active_agreement,
    setup_agreement_with_matched_transactions,
    setup_approved_true_up_with_pool,
    validate_error,
    validate_paginated,
    validate_success,
    api_client,
)


class TestComputePreconditions:

    def test_compute_without_matched_transactions_rejected(self):
        """PRD section 3.5: "Computation (`DRAFT → COMPUTED`) requires at
        least one transaction for the agreement and year with an
        `elimination_status` of `MATCHED` or `ELIMINATED`; an empty input set
        is rejected with `ERR_NO_ELIMINATED_TRANSACTIONS`."

        Design: Corner/errors/compute_without_matched_transactions_rejected
        """
        ctx = setup_active_agreement()
        run = create_run(ctx["agreement"]["id"], ctx["fiscal_year"]["id"])

        resp = api_client.compute_true_up_run(run["id"], ANALYST)
        validate_error(resp, ApiErrorId.ERR_NO_ELIMINATED_TRANSACTIONS)

        after = validate_success(api_client.get_true_up_run(run["id"], MANAGER),
                                 200)
        assert after["status"] == "DRAFT"

    def test_compute_twice_rejected(self):
        """PRD section 3.5: "Computation (`DRAFT → COMPUTED`) requires at
        least one transaction for the agreement and year with an
        `elimination_status` of `MATCHED` or `ELIMINATED`"
        PRD section 2.8: "4. **State legality** — the target resource must be
        in a state from which the requested transition or operation is
        defined, else `ERR_INVALID_STATE_TRANSITION` (HTTP 409)."

        Design: Corner/state_machines/true_up_compute_twice_rejected
        """
        ctx = setup_agreement_with_matched_transactions(
            tx_specs=((1_000_000, 1_020_000),))
        run = create_computed_run(ctx["agreement"]["id"],
                                  ctx["fiscal_year"]["id"])
        assert run["status"] == "COMPUTED"

        resp = api_client.compute_true_up_run(run["id"], ANALYST)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

        after = validate_success(api_client.get_true_up_run(run["id"], MANAGER),
                                 200)
        assert after["status"] == "COMPUTED"


class TestComputeInputSet:

    def test_unmatched_transactions_excluded_from_true_up(self):
        """PRD section 3.5: "The tested set is exactly those `MATCHED` and
        `ELIMINATED` transactions — `UNMATCHED` bookings are excluded."
        PRD section 3.5: "The run aggregates the set's total cost base and
        total booked provider revenue, then derives the `actual_margin_bp`:
        the excess of total booked revenue over total cost base, multiplied
        by 10000, divided by the total cost base, rounded half-up."

        Design: Corner/calculations/unmatched_transactions_excluded_from_true_up_input
        """
        ctx = setup_active_agreement()
        book_and_match(ctx["agreement"]["id"], ctx["fiscal_year"]["id"],
                       1_000_000, 1_020_000)
        # A 9x-larger UNMATCHED booking must be excluded from the tested set.
        book_transaction(ctx["agreement"]["id"], ctx["fiscal_year"]["id"],
                         9_000_000, 9_000_000)
        run = create_run(ctx["agreement"]["id"], ctx["fiscal_year"]["id"])

        computed = compute_run(run["id"])
        assert computed["actual_margin_bp"] == 200, \
            "margin derives from the single MATCHED transaction alone"
        # target price 1000000 * 1.05 = 1050000; true-up = 1050000 - 1020000
        assert computed["true_up_amount_cents"] == 30_000


class TestTrueUpVariantsDiverge:

    def _setup_median_and_edge_runs(self):
        """Two agreements with identical matched bookings, one TO_MEDIAN and
        one TO_RANGE_EDGE, each with its own DRAFT run."""
        ctx = setup_active_agreement(
            transaction_type="SERVICES", true_up_method="TO_MEDIAN")
        for cost, revenue in ((1_000_000, 1_020_000), (2_000_000, 2_040_000)):
            book_and_match(ctx["agreement"]["id"], ctx["fiscal_year"]["id"],
                           cost, revenue)
        edge_agreement = create_active_agreement(
            ctx["provider"]["id"], ctx["recipient"]["id"], ctx["study"]["id"],
            transaction_type="FINANCING", true_up_method="TO_RANGE_EDGE")
        for cost, revenue in ((1_000_000, 1_020_000), (2_000_000, 2_040_000)):
            book_and_match(edge_agreement["id"], ctx["fiscal_year"]["id"],
                           cost, revenue)
        run_med = create_run(ctx["agreement"]["id"], ctx["fiscal_year"]["id"])
        run_edge = create_run(edge_agreement["id"], ctx["fiscal_year"]["id"])
        return ctx, run_med, run_edge

    def test_true_up_to_median_target(self):
        """PRD section 3.5: "Outside the range, the target margin depends on
        the agreement's `true_up_method`: under `TO_MEDIAN` the target is the
        pinned median"
        PRD section 3.5: "The target price is then the total cost base
        multiplied by the sum of 10000 and the target margin, divided by
        10000, rounded half-up to whole cents, and the `true_up_amount_cents`
        is that target price minus the total booked revenue — a signed figure
        where a positive amount means the recipient owes the provider."

        Design: Difficulty/dual_variant_calc/true_up_to_median_vs_to_range_edge_diverge
        """
        _, run_med, _ = self._setup_median_and_edge_runs()
        computed = compute_run(run_med["id"])
        # S_cost 3000000, S_booked 3060000 -> margin 200 (outside [400, 600])
        assert computed["actual_margin_bp"] == 200
        # target median 500 -> 3000000 * 1.05 - 3060000 = 90000
        assert computed["true_up_amount_cents"] == 90_000

    def test_true_up_range_edge_target_diverges(self):
        """PRD section 3.5: "under `TO_RANGE_EDGE` the target is whichever of
        the pinned P25 or P75 is closer to the actual margin, with an exact
        tie resolving to the lower edge — the range-edge variant deliberately
        produces a smaller adjustment than the median variant for the same
        data."

        Design: Difficulty/dual_variant_calc/true_up_to_median_vs_to_range_edge_diverge
        """
        _, run_med, run_edge = self._setup_median_and_edge_runs()
        computed_edge = compute_run(run_edge["id"])
        assert computed_edge["actual_margin_bp"] == 200
        # nearest edge to 200 is p25 = 400 -> 3000000 * 1.04 - 3060000
        assert computed_edge["true_up_amount_cents"] == 60_000

        computed_med = compute_run(run_med["id"])
        assert computed_edge["true_up_amount_cents"] != \
            computed_med["true_up_amount_cents"], \
            "the two true-up variants must diverge on identical inputs"


class TestRangeMembershipBranch:

    def test_margin_within_range_yields_zero_true_up(self):
        """PRD section 3.5: "Range membership is inclusive: when the actual
        margin lies at or between the pinned P25 and P75, the
        `true_up_amount_cents` is 0 and no adjustment is needed."

        Design: Difficulty/combinatorial_formula/true_up_multifactor_conditional_branching
        """
        ctx = setup_agreement_with_matched_transactions(
            tx_specs=((2_000_000, 2_100_000),), true_up_method="TO_MEDIAN")
        run = create_run(ctx["agreement"]["id"], ctx["fiscal_year"]["id"])

        computed = compute_run(run["id"])
        # margin = 100000 * 10000 / 2000000 = 500, inside [400, 600]
        assert computed["actual_margin_bp"] == 500
        assert computed["true_up_amount_cents"] == 0

    def test_margin_below_range_adjusts_to_median(self):
        """PRD section 3.5: "Range membership is inclusive: when the actual
        margin lies at or between the pinned P25 and P75, the
        `true_up_amount_cents` is 0 and no adjustment is needed. Outside the
        range, the target margin depends on the agreement's `true_up_method`:
        under `TO_MEDIAN` the target is the pinned median"

        Design: Difficulty/combinatorial_formula/true_up_multifactor_conditional_branching
        """
        ctx = setup_agreement_with_matched_transactions(
            tx_specs=((2_000_000, 2_040_000),), true_up_method="TO_MEDIAN")
        run = create_run(ctx["agreement"]["id"], ctx["fiscal_year"]["id"])

        computed = compute_run(run["id"])
        assert computed["actual_margin_bp"] == 200
        # target 500 -> 2000000 * 1.05 - 2040000 = 60000
        assert computed["true_up_amount_cents"] == 60_000


class TestRangeBoundary:

    def _setup_boundary_runs(self):
        """Agreement A sits exactly at pinned p25 (margin 400); agreement B
        rounds to margin 397 (below the range)."""
        ctx = setup_active_agreement(
            transaction_type="SERVICES", true_up_method="TO_MEDIAN")
        for cost, revenue in ((1_000_000, 1_040_000), (2_000_000, 2_080_000)):
            book_and_match(ctx["agreement"]["id"], ctx["fiscal_year"]["id"],
                           cost, revenue)
        below_agreement = create_active_agreement(
            ctx["provider"]["id"], ctx["recipient"]["id"], ctx["study"]["id"],
            transaction_type="IP_ROYALTY", true_up_method="TO_MEDIAN")
        for cost, revenue in ((1_000_000, 1_039_000), (2_000_000, 2_080_000)):
            book_and_match(below_agreement["id"], ctx["fiscal_year"]["id"],
                           cost, revenue)
        run_bound = create_run(ctx["agreement"]["id"], ctx["fiscal_year"]["id"])
        run_below = create_run(below_agreement["id"], ctx["fiscal_year"]["id"])
        return run_bound, run_below

    def test_margin_at_p25_boundary_in_range(self):
        """PRD section 3.5: "Range membership is inclusive: when the actual
        margin lies at or between the pinned P25 and P75, the
        `true_up_amount_cents` is 0 and no adjustment is needed."

        Design: Difficulty/boundary_precision_check/true_up_margin_at_p25_boundary_is_in_range
        """
        run_bound, _ = self._setup_boundary_runs()
        computed = compute_run(run_bound["id"])
        # S_cost 3000000, S_booked 3120000 -> margin exactly 400 == pinned p25
        assert computed["actual_margin_bp"] == 400
        assert computed["true_up_amount_cents"] == 0, \
            "margin exactly at the pinned P25 is inside the inclusive range"

    def test_margin_below_p25_boundary_out_of_range(self):
        """PRD section 3.5: "Range membership is inclusive: when the actual
        margin lies at or between the pinned P25 and P75, the
        `true_up_amount_cents` is 0 and no adjustment is needed. Outside the
        range, the target margin depends on the agreement's `true_up_method`:
        under `TO_MEDIAN` the target is the pinned median"

        Design: Difficulty/boundary_precision_check/true_up_margin_at_p25_boundary_is_in_range
        """
        _, run_below = self._setup_boundary_runs()
        computed = compute_run(run_below["id"])
        # S_booked 3119000 -> round_half_up(119000 * 10000 / 3000000) = 397
        assert computed["actual_margin_bp"] == 397
        # target median 500 -> 3000000 * 1.05 - 3119000 = 31000
        assert computed["true_up_amount_cents"] == 31_000


class TestApproveGate:

    def _setup_computed_run_year_open(self):
        ctx = setup_agreement_with_matched_transactions(
            tx_specs=((1_000_000, 1_020_000),))
        run = create_computed_run(ctx["agreement"]["id"],
                                  ctx["fiscal_year"]["id"])
        return ctx, run

    def test_approve_requires_year_closing(self):
        """PRD section 3.5: "Approval by a `TaxManager` (`COMPUTED →
        APPROVED`) requires the fiscal year to be `CLOSING`
        (`ERR_YEAR_NOT_CLOSING`) and the approver to differ from the run's
        `created_by_user_id` (`ERR_SEGREGATION_OF_DUTIES`)"

        Design: Difficulty/cross_entity_state_dependency/true_up_approve_requires_fiscal_year_closing
        """
        ctx, run = self._setup_computed_run_year_open()
        assert ctx["fiscal_year"]["status"] == "OPEN"

        resp = api_client.approve_true_up_run(run["id"], MANAGER)
        validate_error(resp, ApiErrorId.ERR_YEAR_NOT_CLOSING)

    def test_approve_succeeds_once_year_closing(self):
        """PRD section 3.5: "Approval by a `TaxManager` (`COMPUTED →
        APPROVED`) requires the fiscal year to be `CLOSING`
        (`ERR_YEAR_NOT_CLOSING`) and the approver to differ from the run's
        `created_by_user_id` (`ERR_SEGREGATION_OF_DUTIES`); it records
        `approved_by_user_id`."

        Design: Difficulty/cross_entity_state_dependency/true_up_approve_requires_fiscal_year_closing
        """
        ctx, run = self._setup_computed_run_year_open()
        begin_closing(ctx["fiscal_year"]["id"])

        approved = approve_run(run["id"])
        assert approved["status"] == "APPROVED"
        assert approved["approved_by_user_id"] == "mgr-1"


class TestPostCascade:

    def test_post_creates_auto_eliminated_adjustment(self):
        """PRD section 3.5: "First, when the `true_up_amount_cents` is not 0,
        the server creates an adjustment transaction for the same agreement
        and year with `cost_base_cents` of 0, both `provider_revenue_cents`
        and `recipient_cost_cents` equal to the true-up amount,
        `origin_run_id` pointing at the run, `is_true_up_adjustment` true,
        `elimination_status` `MATCHED`, and `settlement_status` `UNSETTLED`,
        and records its identifier as the run's `adjustment_transaction_id`"
        PRD section 3.5: "Second, the adjustment is immediately
        auto-eliminated to `ELIMINATED` with a plug of 0."

        Design: Difficulty/transitive_cascade/true_up_post_cascades_adjustment_elimination_pool_accrual
        """
        ctx = setup_approved_true_up_with_pool()
        posted = post_run(ctx["run"]["id"])
        assert posted["status"] == "POSTED"

        adj_id = posted["adjustment_transaction_id"]
        assert adj_id is not None
        adj = validate_success(api_client.get_transaction(adj_id, MANAGER), 200)
        assert adj["is_true_up_adjustment"] is True
        assert adj["origin_run_id"] == posted["id"]
        assert adj["provider_revenue_cents"] == 90_000
        assert adj["recipient_cost_cents"] == 90_000
        assert adj["cost_base_cents"] == 0
        assert adj["elimination_status"] == "ELIMINATED", \
            "link 2: the adjustment is auto-eliminated by its own creation"

    def test_post_accrues_pending_into_open_pool(self):
        """PRD section 3.5: "Third, if a cash pool exists for the fiscal year
        in status `OPEN`, the provider entity's position `pending_cents` is
        increased by the true-up amount and the recipient entity's position
        `pending_cents` is decreased by the same amount, with positions
        upserted per entity as needed."
        PRD section 3.4: "the invariant that
        `consolidated_intercompany_net_cents` equals 0 holds after every
        elimination batch."

        Design: Difficulty/transitive_cascade/true_up_post_cascades_adjustment_elimination_pool_accrual
        """
        ctx = setup_approved_true_up_with_pool()
        post_run(ctx["run"]["id"])

        pool = validate_success(api_client.get_cash_pool(ctx["pool"]["id"],
                                                         TREASURY), 200)
        provider_pos = find_position(pool, ctx["provider"]["id"])
        recipient_pos = find_position(pool, ctx["recipient"]["id"])
        assert provider_pos["pending_cents"] == 90_000
        assert recipient_pos["pending_cents"] == -90_000

        year = validate_success(
            api_client.get_fiscal_year(ctx["fiscal_year"]["id"], ADMIN), 200)
        assert year["consolidated_intercompany_net_cents"] == 0


class TestZeroAmountPost:

    def test_zero_true_up_post_creates_no_adjustment(self):
        """PRD section 3.5: "when the amount is 0 no adjustment is created
        and the field stays null."
        PRD section 3.5: "The true-up runs listing accepts optional filters
        `agreement_id`, `fiscal_year_id`, `adjustment_transaction_id`, and
        `status`."
        PRD section 3.4: "The transactions listing accepts optional filters
        `agreement_id`, `fiscal_year_id`, `origin_run_id`,
        `elimination_status`, and `settlement_status`."

        Design: Corner/errors/zero_true_up_post_creates_no_adjustment
        """
        # Margin exactly 500 (the pinned median) is inside [400, 600].
        ctx = setup_agreement_with_matched_transactions(
            tx_specs=((1_000_000, 1_050_000),))
        begin_closing(ctx["fiscal_year"]["id"])
        run = create_computed_run(ctx["agreement"]["id"],
                                  ctx["fiscal_year"]["id"])
        assert run["true_up_amount_cents"] == 0
        approve_run(run["id"])

        posted = post_run(run["id"])
        assert posted["status"] == "POSTED"
        assert posted["true_up_amount_cents"] == 0
        assert posted["adjustment_transaction_id"] is None

        resp = api_client.list_transactions(
            MANAGER, params={"origin_run_id": run["id"]})
        data, meta = validate_paginated(resp)
        assert meta["total_count"] == 0
        assert data == []
