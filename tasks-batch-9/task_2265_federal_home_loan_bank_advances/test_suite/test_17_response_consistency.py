"""Immediate consistency: the two heaviest writes in the domain are readable in full the
instant they return, with every sibling entity and every read path already agreeing."""
from test_helpers import *  # noqa: F401,F403


class TestFundingIsVisibleImmediately:
    """One call moves an advance, a member, a posture and a stock subscription."""

    def _funded_with_stock_from_the_advance(self, api):
        """950,000 of cash plus 50,000 of activity stock, approved then funded."""
        env = member_with_eligible_sf(api)
        product = create_product(api)
        advance = request_advance(
            api,
            env,
            product["id"],
            term_days=30,
            requested_net_proceeds_cents=950_000,
            fund_stock_from_advance=True,
        )
        validate_success(api.approve_advance(advance["id"], CREDIT_ONE))
        return env, advance, api.fund_advance(advance["id"], CREDIT_TWO)

    def test_the_funding_response_already_carries_every_derived_figure(self, api):
        """PRD §3.6: "`funded_by_user_id` records the acting `X-User-ID`, `funded_at` is
        stamped with the logical-clock instant, `maturity_date` is set to `funded_at` plus
        `term_days`, and `outstanding_principal_cents` is set to
        `gross_principal_cents`."

        Design: Corner/consistency_model/funding_response_already_reflects_every_derived_field
        """
        env, _advance, response = self._funded_with_stock_from_the_advance(api)

        funded = assert_envelope(response)
        assert_advance_dimensions(funded, "FUNDED", "SECURED")
        assert_fields(
            funded,
            gross_principal_cents=1_000_000,
            net_proceeds_cents=950_000,
            outstanding_principal_cents=1_000_000,
            funded_by_user_id=CREDIT_OFFICER_TWO_USER_ID,
            funded_at="2026-08-01T00:00:00.000Z",
            maturity_date="2026-08-31T00:00:00.000Z",
            capacity_at_funding_cents=15_600_000,
        )
        member = env.refresh()
        assert_fields(
            member,
            total_outstanding_advances_cents=1_000_000,
            committed_advances_cents=0,
            borrowing_capacity_cents=14_600_000,
            collateral_posture="OPEN",
        )

    def test_no_read_path_lags_another_after_the_money_moves(self, api):
        """PRD §3.6: "When `fund_stock_from_advance` is true, an `ACTIVITY` subscription of
        `amount_cents` equal to `activity_stock_cents` is created with its `advance_id`
        pointing at this advance and is immediately `ISSUED` in the same request — its
        `SUBSCRIBED` state is never observable on this path."

        Design: Corner/consistency_model/funding_response_already_reflects_every_derived_field
        """
        env, advance, response = self._funded_with_stock_from_the_advance(api)
        validate_success(response)

        rows = assert_total_count(
            api.list_stock_subscriptions(CREDIT_ONE), 2
        )
        activity = [row for row in rows if row["subscription_type"] == "ACTIVITY"]

        assert len(activity) == 1
        assert_fields(
            activity[0],
            amount_cents=50_000,
            status="ISSUED",
            advance_id=advance["id"],
        )
        assert_capacity_breakdown(
            env.capacity("CERTIFIED"),
            lendable_collateral_value_cents=15_600_000,
            outstanding_advances_cents=1_000_000,
            commitments_cents=0,
            borrowing_capacity_cents=14_600_000,
        )
        assert env.refresh()["stock_held_cents"] == 9_650_000


class TestReviewCloseIsVisibleImmediately:
    """The deepest cascade in the domain is still one synchronous request."""

    def _closed_over_one_major_finding(self, api):
        """A single MAJOR finding on a sample of 20 is exactly 5.00 percent."""
        env = member_with_eligible_sf(api)
        review, findings = review_with_findings_issued(
            api,
            env,
            env.assets["sf"]["id"],
            window_start=CLOCK_START,
            window_end="2026-08-10T00:00:00Z",
            sample_size=20,
        )
        return env, findings[0], api.close_review(review["id"], AUDITOR)

    def test_the_close_response_carries_the_computed_band(self, api):
        """PRD §3.8: "Every finding of this review still `OPEN` moves to `UNRESOLVED`;
        `closed_at` is stamped from the logical clock; and the member's
        `verification_haircut_bps` is set to this review's `haircut_bps` while
        `latest_review_outcome` is set to this review's `outcome`."

        Design: Corner/consistency_model/review_close_cascade_is_visible_without_a_refetch
        """
        _env, finding, response = self._closed_over_one_major_finding(api)

        closed = assert_envelope(response)
        assert_fields(
            closed,
            status="CLOSED",
            haircut_bps=700,
            outcome="QUALIFIED",
            closed_at="2026-08-01T00:00:00.000Z",
        )
        assert_weighted_score(closed, 1.0)
        assert_exception_rate(closed, 5.00)
        assert (
            get_success_data(api.get_review_finding(finding["id"], AUDITOR))["status"]
            == "UNRESOLVED"
        )

    def test_the_suspended_asset_and_the_resized_member_are_readable_at_once(self, api):
        """PRD §3.8: "In addition, every `ELIGIBLE` asset carrying an `UNRESOLVED` finding
        from this review whose `severity` is `MAJOR` or `CRITICAL` transitions `ELIGIBLE →
        SUSPENDED`, with `lendable_value_cents` set to 0, `discount_factor_bps` set to 0 and
        `ineligibility_reason` set to `UNRESOLVED_REVIEW_FINDING`."

        Design: Corner/consistency_model/review_close_cascade_is_visible_without_a_refetch
        """
        env, _finding, response = self._closed_over_one_major_finding(api)
        validate_success(response)

        asset = read_asset(api, env.assets["sf"]["id"])
        member = env.refresh()

        assert_fields(
            asset,
            status="SUSPENDED",
            ineligibility_reason="UNRESOLVED_REVIEW_FINDING",
        )
        assert_asset_valuation(asset, 0, 0)
        assert_fields(
            member,
            verification_haircut_bps=700,
            latest_review_outcome="QUALIFIED",
            lendable_collateral_value_cents=0,
            borrowing_capacity_cents=0,
            shortfall_status="NONE",
            collateral_posture="OPEN",
        )
        assert_capacity_breakdown(
            env.capacity("CERTIFIED"),
            lendable_collateral_value_cents=0,
            borrowing_capacity_cents=0,
        )
