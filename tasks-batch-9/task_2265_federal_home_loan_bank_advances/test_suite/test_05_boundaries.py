"""Two edges measured exactly: a haircut band's lower bound reached to the cent of a
percentage point, and a borrowing capacity of exactly zero over an empty portfolio."""
from test_helpers import *  # noqa: F401,F403


class TestExceptionRateBandEdge:
    """4.375 rounds to 4.38 and takes the 300 band; 5.00 exactly takes the 700 band."""

    def _member_with_two_consecutive_reviews(self, api):
        """Three eligible assets; review one closes below the edge, review two sits on it."""
        env = member_with_eligible_sf(api)
        add_heloc(api, env, key="heloc_a")
        add_heloc(api, env, ltv_bps=6_500, key="heloc_b")
        first, _findings = closed_review(
            api,
            env,
            env.assets["heloc_a"]["id"],
            severities=("MAJOR", "MINOR", "MINOR", "MINOR"),
            window_start="2026-08-01T00:00:00Z",
            window_end="2026-08-10T00:00:00Z",
        )
        pin_clock(api, "2026-08-10T00:00:00Z")
        second, _more = review_with_findings_issued(
            api,
            env,
            env.assets["heloc_b"]["id"],
            severities=("MAJOR", "MAJOR"),
            window_start="2026-08-10T00:00:00Z",
            window_end="2026-08-20T00:00:00Z",
        )
        return env, first, second

    def test_a_rate_of_four_point_three_seven_five_rounds_half_up_and_takes_the_lower_band(self, api):
        """PRD §3.8: "`exception_rate_pct` is 100 multiplied by
        `weighted_exception_score`, divided by `sample_size`, rounded half up to
        exactly two decimal places."

        Design: Difficulty/boundary_precision_check/exception_rate_exactly_five_percent_selects_seven_hundred_bps_band
        """
        _env, first, _second = self._member_with_two_consecutive_reviews(api)

        assert_weighted_score(first, 1.75)
        assert_exception_rate(first, 4.38)
        assert_fields(first, haircut_bps=300, outcome="QUALIFIED")

    def test_the_lower_band_reprices_the_portfolio_at_three_hundred_basis_points(self, api):
        """PRD §3.4: "Then subtract the owning member's `verification_haircut_bps`, the
        standing penalty left behind by its most recent closed verification review."

        Design: Difficulty/boundary_precision_check/exception_rate_exactly_five_percent_selects_seven_hundred_bps_band
        """
        env, _first, _second = self._member_with_two_consecutive_reviews(api)

        member = env.refresh()

        assert member["verification_haircut_bps"] == 300
        assert_asset_valuation(read_asset(api, env.assets["sf"]["id"]), 7_500, 15_000_000)
        assert_asset_valuation(
            read_asset(api, env.assets["heloc_b"]["id"]), 4_700, 470_000
        )
        assert_fields(
            read_asset(api, env.assets["heloc_a"]["id"]),
            status="SUSPENDED",
            lendable_value_cents=0,
        )
        assert member["lendable_collateral_value_cents"] == 15_470_000

    def test_a_rate_of_exactly_five_percent_takes_the_seven_hundred_band(self, api):
        """PRD §3.8: "`haircut_bps` is then selected by band from that rounded
        percentage, with every lower bound inclusive: 0 basis points below 2.00
        percent; 300 basis points from 2.00 percent up to but not including 5.00
        percent; 700 basis points from 5.00 percent up to but not including 10.00
        percent; and 1,500 basis points at 10.00 percent or above."

        Design: Difficulty/boundary_precision_check/exception_rate_exactly_five_percent_selects_seven_hundred_bps_band
        """
        _env, _first, second = self._member_with_two_consecutive_reviews(api)

        closed = close_review(api, second["id"])

        assert_weighted_score(closed, 2.0)
        assert_exception_rate(closed, 5.00)
        assert closed["haircut_bps"] == 700
        assert closed["haircut_bps"] != 300
        assert closed["outcome"] == "QUALIFIED"

    def test_the_seven_hundred_band_reprices_the_portfolio_again(self, api):
        """PRD §3.8: "**Level two — repricing the collateral.** Because the member's
        `verification_haircut_bps` changed, every collateral asset of that member whose
        `status` is `ELIGIBLE` or `SUSPENDED` has its `discount_factor_bps` and
        `lendable_value_cents` recomputed with the new haircut subtracted."

        Design: Difficulty/boundary_precision_check/exception_rate_exactly_five_percent_selects_seven_hundred_bps_band
        """
        env, _first, second = self._member_with_two_consecutive_reviews(api)

        close_review(api, second["id"])

        member = env.refresh()
        assert member["verification_haircut_bps"] == 700
        assert_asset_valuation(read_asset(api, env.assets["sf"]["id"]), 7_100, 14_200_000)
        assert_fields(
            read_asset(api, env.assets["heloc_b"]["id"]),
            status="SUSPENDED",
            lendable_value_cents=0,
        )
        assert member["lendable_collateral_value_cents"] == 14_200_000


class TestZeroCapacityBoundary:
    """An executed pledge and no approved assets leave capacity at exactly zero."""

    def _active_member_with_no_collateral(self, api):
        env = pledging_member(api)
        product = create_product(api)
        return env, product

    def test_an_empty_eligible_set_produces_a_capacity_of_exactly_zero(self, api):
        """PRD §3.5: "Third, the capacity base is the lesser of two rounded terms: the
        member's lendable collateral value multiplied by the tier cap, divided by
        10,000, rounded half up to whole cents; and the statutory cap."

        Design: Difficulty/boundary_precision_check/zero_eligible_assets_capacity_boundary_rejects_advance
        """
        env, _product = self._active_member_with_no_collateral(api)

        breakdown = env.capacity(variant="PROVISIONAL")

        assert_capacity_breakdown(
            breakdown,
            lendable_collateral_value_cents=0,
            tier_cap_bps=10_000,
            statutory_cap_cents=2_400_000_000,
            capacity_base_cents=0,
            outstanding_advances_cents=0,
            commitments_cents=0,
            borrowing_capacity_cents=0,
        )

    def test_a_capacity_of_exactly_zero_is_stored_and_leaves_the_posture_open(self, api):
        """PRD §2.8: "Observe the corollary: when the member has no outstanding
        advances the buffer term is 0, so a capacity of exactly 0 is not made
        `RESTRICTED` by the buffer clause."

        Design: Difficulty/boundary_precision_check/zero_eligible_assets_capacity_boundary_rejects_advance
        """
        env, _product = self._active_member_with_no_collateral(api)

        member = env.refresh()

        assert member["lendable_collateral_value_cents"] == 0
        assert member["borrowing_capacity_cents"] == 0
        assert member["borrowing_capacity_cents"] is not None
        assert_fields(
            member, total_outstanding_advances_cents=0, collateral_posture="OPEN"
        )

    def test_the_capacity_gate_still_applies_to_an_empty_portfolio(self, api):
        """PRD §3.5: "Advance creation is gated on the **provisional** variant, because
        the request being created is not yet a commitment: if `gross_principal_cents`
        exceeds the member's provisional capacity, the request is rejected with
        `ERR_INSUFFICIENT_BORROWING_CAPACITY`."

        Design: Difficulty/boundary_precision_check/zero_eligible_assets_capacity_boundary_rejects_advance
        """
        env, product = self._active_member_with_no_collateral(api)
        version_before = env.version

        response = api.create_advance(
            advance_payload(
                env.member_id,
                product["id"],
                version_before,
                term_days=360,
                requested_net_proceeds_cents=1_000_000,
                fund_stock_from_advance=False,
            ),
            env.treasury,
        )

        validate_error(response, "ERR_INSUFFICIENT_BORROWING_CAPACITY", 409)
        assert_total_count(
            api.list_advances(CREDIT_ONE, {"member_bank_id": env.member_id}), 0
        )
        assert env.version == version_before
