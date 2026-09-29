"""Borrowing capacity variants, prepayment fee variants, and the two formulas
whose answer depends on how their terms are combined."""
from test_helpers import *  # noqa: F401,F403


class TestBorrowingCapacityVariants:
    """The provisional and certified variants of the same capacity formula."""

    def _member_with_both_variants_diverging(self, api):
        """One eligible asset, one under review, one requested and one approved advance."""
        env = member_with_eligible_sf(api)
        pledge_asset(
            api,
            env.member_id,
            unpaid_principal_balance_cents=10_000_000,
            market_value_cents=12_000_000,
            ltv_bps=7_000,
        )
        product = create_product(api, prepayment_fee_method="SYMMETRIC_MARKET_VALUE")
        requested = request_advance(
            api,
            env,
            product["id"],
            requested_net_proceeds_cents=5_000_000,
            fund_stock_from_advance=False,
        )
        approved = request_advance(
            api,
            env,
            product["id"],
            requested_net_proceeds_cents=3_000_000,
            fund_stock_from_advance=False,
        )
        approve_advance(api, approved["id"])
        return env, requested, approved

    def test_provisional_variant_credits_under_review_assets_and_drops_requested_commitments(self, api):
        """PRD §3.5: "The **provisional** variant takes lendable collateral from the
        provisional aggregate — which additionally credits `UNDER_REVIEW` assets at
        half of their hypothetical lendable value — and counts as commitments only
        advances whose `credit_status` is `CREDIT_APPROVED`, excluding `REQUESTED`
        ones."

        Design: Difficulty/dual_variant_calc/borrowing_capacity_provisional_versus_certified_diverge
        """
        env, _requested, _approved = self._member_with_both_variants_diverging(api)

        breakdown = env.capacity(variant="PROVISIONAL")

        assert_capacity_breakdown(
            breakdown,
            variant="PROVISIONAL",
            lendable_collateral_value_cents=19_500_000,
            commitments_cents=3_000_000,
            capacity_base_cents=19_500_000,
            borrowing_capacity_cents=16_500_000,
        )

    def test_certified_variant_stored_on_the_member_counts_only_eligible_assets(self, api):
        """PRD §3.5: "The **certified** variant takes lendable collateral from the
        certified aggregate — `ELIGIBLE` assets only — counts as outstanding the sum
        of `outstanding_principal_cents` over advances whose `credit_status` is
        `FUNDED`, and counts as commitments the sum of `gross_principal_cents` over
        advances whose `credit_status` is `REQUESTED` or `CREDIT_APPROVED`."

        Design: Difficulty/dual_variant_calc/borrowing_capacity_provisional_versus_certified_diverge
        """
        env, _requested, _approved = self._member_with_both_variants_diverging(api)

        member = env.refresh()

        assert_fields(
            member,
            lendable_collateral_value_cents=15_600_000,
            borrowing_capacity_cents=7_600_000,
            committed_advances_cents=8_000_000,
        )
        certified = env.capacity(variant="CERTIFIED")
        assert_capacity_breakdown(
            certified,
            variant="CERTIFIED",
            lendable_collateral_value_cents=15_600_000,
            commitments_cents=8_000_000,
            borrowing_capacity_cents=7_600_000,
        )

    def test_two_variants_differ_for_identical_stored_data(self, api):
        """PRD §3.5: "It therefore reports a larger figure than the certified variant,
        for identical data, whenever either an `UNDER_REVIEW` asset or a `REQUESTED`
        advance exists."

        Design: Difficulty/dual_variant_calc/borrowing_capacity_provisional_versus_certified_diverge
        """
        env, _requested, _approved = self._member_with_both_variants_diverging(api)

        provisional = env.capacity(variant="PROVISIONAL")
        certified = env.capacity(variant="CERTIFIED")

        assert provisional["borrowing_capacity_cents"] == 16_500_000
        assert certified["borrowing_capacity_cents"] == 7_600_000
        assert (
            provisional["borrowing_capacity_cents"]
            - certified["borrowing_capacity_cents"]
            == 8_900_000
        )


class TestPrepaymentFeeVariants:
    """The quote variant and the settlement variant of the same fee formula."""

    def _funded_advance_ready_to_prepay(self, api):
        """A 30,000,000 advance at 425 basis points funded on the clock's start date."""
        pin_clock(api)
        set_market_rate(api, 300)
        env = member_with_eligible_sf(api)
        add_cre(api, env)
        subscribe_and_issue(api, env.member_id, 1_350_000, "ACTIVITY")
        product = create_product(
            api,
            prepayment_fee_method="SYMMETRIC_MARKET_VALUE",
            symmetric_credit_enabled=False,
        )
        advance = funded_advance(
            api,
            env,
            product["id"],
            term_days=360,
            requested_net_proceeds_cents=30_000_000,
            fund_stock_from_advance=False,
        )
        return env, advance

    def test_quote_variant_prices_the_remaining_term_without_an_administrative_fee(self, api):
        """PRD §3.7: "The **quote** variant uses the market rate in effect at
        `quote_date`, snapshotted into `quoted_market_rate_bps`; uses the remaining
        days measured from `quote_date`; adds **no** administrative fee; and stores
        its result in `quoted_fee_cents`."

        Design: Difficulty/dual_variant_calc/prepayment_fee_quote_versus_settlement_diverge
        """
        env, advance = self._funded_advance_ready_to_prepay(api)
        assert advance["maturity_date"].startswith("2027-07-27")

        pin_clock(api, "2026-11-01T00:00:00Z")
        event = quote_prepayment(api, env, advance["id"], 30_000_000, "FULL")

        assert_fields(
            event,
            status="QUOTED",
            quoted_market_rate_bps=300,
            quoted_remaining_days=268,
            quoted_fee_cents=279_167,
            admin_fee_cents=0,
            symmetric_credit_cents=0,
        )
        assert event["settled_fee_cents"] is None
        assert event["fee_delta_cents"] is None

    def test_settlement_variant_reprices_at_the_settlement_rate_and_adds_the_admin_fee(self, api):
        """PRD §3.7: "The **settlement** variant uses the market rate in effect at
        `settlement_date`, stored in `settlement_market_rate_bps`; uses
        `settled_remaining_days` measured from `settlement_date`; and **adds** an
        administrative fee, `admin_fee_cents`, computed as `prepay_amount_cents`
        multiplied by 5 basis points, divided by 10,000, rounded half up."

        Design: Difficulty/dual_variant_calc/prepayment_fee_quote_versus_settlement_diverge
        """
        env, advance = self._funded_advance_ready_to_prepay(api)
        pin_clock(api, "2026-11-01T00:00:00Z")
        event = quote_prepayment(api, env, advance["id"], 30_000_000, "FULL")

        pin_clock(api, "2026-11-03T00:00:00Z")
        set_market_rate(api, 250)
        settled = settle_prepayment(api, event["id"])

        assert_fields(
            settled,
            status="SETTLED",
            settlement_market_rate_bps=250,
            settled_remaining_days=266,
            admin_fee_cents=15_000,
            settled_fee_cents=402_917,
            symmetric_credit_cents=0,
        )

    def test_fee_delta_is_the_settled_figure_minus_the_quoted_figure(self, api):
        """PRD §3.7: "`fee_delta_cents` is `settled_fee_cents` minus
        `quoted_fee_cents`."

        Design: Difficulty/dual_variant_calc/prepayment_fee_quote_versus_settlement_diverge
        """
        env, advance = self._funded_advance_ready_to_prepay(api)
        pin_clock(api, "2026-11-01T00:00:00Z")
        event = quote_prepayment(api, env, advance["id"], 30_000_000, "FULL")

        pin_clock(api, "2026-11-03T00:00:00Z")
        set_market_rate(api, 250)
        settled = settle_prepayment(api, event["id"])

        assert settled["quoted_fee_cents"] == 279_167
        assert settled["settled_fee_cents"] == 402_917
        assert settled["fee_delta_cents"] == 123_750
        assert read_advance(api, advance["id"])["credit_status"] == "PREPAID"


class TestLendableValueAggregationOrder:
    """Rounding each asset before summing, not summing then rounding."""

    def _two_assets_rounding_in_opposite_directions(self, api):
        env = pledging_member(api)
        first = pledge_asset(
            api,
            env.member_id,
            unpaid_principal_balance_cents=12_345_679,
            market_value_cents=20_000_000,
            ltv_bps=7_500,
        )
        review_asset(api, first["id"])
        second = pledge_asset(
            api,
            env.member_id,
            unpaid_principal_balance_cents=12_345_678,
            market_value_cents=20_000_000,
            ltv_bps=7_500,
        )
        review_asset(api, second["id"])
        return env, first, second

    def test_each_asset_is_rounded_half_up_to_whole_cents_on_its_own(self, api):
        """PRD §3.4: "`lendable_value_cents` for a single asset is
        `collateral_basis_cents` multiplied by `discount_factor_bps`, divided by
        10,000, rounded half up to whole cents."

        Design: Difficulty/combinatorial_formula/lendable_value_rounds_per_asset_before_summing
        """
        _env, first, second = self._two_assets_rounding_in_opposite_directions(api)

        first_row = read_asset(api, first["id"])
        second_row = read_asset(api, second["id"])

        assert_fields(
            first_row,
            collateral_basis_cents=12_345_679,
            discount_factor_bps=7_800,
            lendable_value_cents=9_629_630,
        )
        assert_fields(
            second_row,
            collateral_basis_cents=12_345_678,
            discount_factor_bps=7_800,
            lendable_value_cents=9_629_629,
        )

    def test_member_aggregate_sums_the_rounded_per_asset_figures_exactly(self, api):
        """PRD §3.4: "Each asset is rounded to whole cents first and the rounded
        per-asset figures are then summed exactly; summing unrounded products and
        rounding once at the end is not the specified behaviour."

        Design: Difficulty/combinatorial_formula/lendable_value_rounds_per_asset_before_summing
        """
        env, _first, _second = self._two_assets_rounding_in_opposite_directions(api)

        member = env.refresh()

        assert member["lendable_collateral_value_cents"] == 19_259_259
        assert member["lendable_collateral_value_cents"] != 19_259_258
        assert member["borrowing_capacity_cents"] == 19_259_259


class TestAdvanceGrossUp:
    """The activity stock obligation resolved inside the principal that funds it."""

    def _requested_grossed_up_advance(self, api):
        env = member_with_eligible_sf(api)
        product = create_product(api)
        advance = request_advance(
            api,
            env,
            product["id"],
            term_days=360,
            requested_net_proceeds_cents=5_000_000,
            fund_stock_from_advance=True,
        )
        return env, advance

    def test_stock_is_computed_from_the_provisional_gross_and_ceiled_to_par(self, api):
        """PRD §3.5: "**Step two** computes `activity_stock_cents` from that
        provisional gross and from nothing else: multiply the provisional gross by
        the stock rate, divide by 10,000, round half up to whole cents, then round up
        to the par multiple."

        Design: Difficulty/combinatorial_formula/advance_gross_up_resolves_stock_inside_principal
        """
        _env, advance = self._requested_grossed_up_advance(api)

        assert advance["activity_stock_cents"] == 240_000
        assert advance["activity_stock_cents"] != 230_000
        assert_par_multiple(advance["activity_stock_cents"])

    def test_gross_principal_is_the_requested_net_plus_the_resolved_stock(self, api):
        """PRD §3.5: "**Step three** sets `gross_principal_cents` to
        `requested_net_proceeds_cents` plus `activity_stock_cents`, an exact
        addition. `net_proceeds_cents` remains `requested_net_proceeds_cents`."

        Design: Difficulty/combinatorial_formula/advance_gross_up_resolves_stock_inside_principal
        """
        _env, advance = self._requested_grossed_up_advance(api)

        assert advance["gross_principal_cents"] == 5_240_000
        assert advance["gross_principal_cents"] != 5_230_000
        assert advance["net_proceeds_cents"] == 5_000_000

    def test_requested_advance_records_its_rate_and_the_provisional_capacity_it_used(self, api):
        """PRD §3.5: "Advance creation is gated on the **provisional** variant,
        because the request being created is not yet a commitment: if
        `gross_principal_cents` exceeds the member's provisional capacity, the
        request is rejected with `ERR_INSUFFICIENT_BORROWING_CAPACITY`. The
        provisional figure that was used is preserved on the advance as
        `capacity_at_request_cents`."

        Design: Difficulty/combinatorial_formula/advance_gross_up_resolves_stock_inside_principal
        """
        _env, advance = self._requested_grossed_up_advance(api)

        assert_fields(
            advance,
            rate_bps=425,
            credit_status="REQUESTED",
            capacity_at_request_cents=15_600_000,
        )
