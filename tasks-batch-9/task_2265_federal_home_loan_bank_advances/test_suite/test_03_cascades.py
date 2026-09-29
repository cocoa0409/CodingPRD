"""Chains in which every link is caused by the link before it: an audit close that
reaches a subsidy pool, and a cash settlement that reaches a sibling advance."""
from test_helpers import *  # noqa: F401,F403


def _read_allocation(api, allocation_id):
    return get_success_data(
        api.get_community_program_allocation(allocation_id, COMMUNITY)
    )


class TestReviewCloseCascade:
    """Closing a failing review: scoring, repricing, capacity, freeze, release."""

    def _member_at_the_moment_of_close(self, api):
        """Three eligible assets, one funded and two community advances, review issued."""
        env = member_with_eligible_sf(api)
        add_cre(api, env)
        add_heloc(api, env)
        subscribe_and_issue(api, env.member_id, 1_350_000, "ACTIVITY")
        plain = create_product(api)
        community = create_product(
            api,
            product_code="CIP-450",
            prepayment_fee_method="NONE",
            min_principal_cents=500_000,
            community_program_flag=True,
        )
        allocation = create_allocation(api)
        env.advances["d"] = funded_advance(
            api,
            env,
            plain["id"],
            term_days=360,
            requested_net_proceeds_cents=30_000_000,
            fund_stock_from_advance=False,
        )
        env.advances["e"] = approved_advance(
            api,
            env,
            community["id"],
            term_days=360,
            requested_net_proceeds_cents=1_500_000,
            fund_stock_from_advance=False,
            community_program_allocation_id=allocation["id"],
            community_bucket="FIRST_TIME_HOMEBUYER",
            requested_subsidy_cents=300_000,
        )
        env.advances["f"] = approved_advance(
            api,
            env,
            community["id"],
            term_days=360,
            requested_net_proceeds_cents=1_000_000,
            fund_stock_from_advance=False,
            community_program_allocation_id=allocation["id"],
            community_bucket="REHABILITATION",
            requested_subsidy_cents=100_000,
        )
        review, findings = review_with_findings_issued(
            api, env, env.assets["heloc"]["id"], severities=("MAJOR",) * 4
        )
        before = _read_allocation(api, allocation["id"])
        return env, allocation["id"], review, findings, before

    def test_level_one_scores_the_review_and_sets_the_member_haircut(self, api):
        """PRD §3.8: "**Level one — scoring the review.** `weighted_exception_score` is
        a weighted count over the findings of this review whose `status` is `OPEN` or
        `UNRESOLVED` at the moment of close: three times the number of `CRITICAL` such
        findings, plus one times the number of `MAJOR` such findings, plus a quarter
        times the number of `MINOR` such findings."

        Design: Difficulty/transitive_cascade/review_close_fail_cascades_five_levels_to_subsidy_release
        """
        env, _allocation_id, review, findings, _before = self._member_at_the_moment_of_close(api)

        closed = close_review(api, review["id"])

        assert_weighted_score(closed, 4.0)
        assert_exception_rate(closed, 10.00)
        assert_fields(
            closed,
            haircut_bps=1_500,
            outcome="FAIL",
            status="CLOSED",
            closed_at="2026-08-01T00:00:00.000Z",
        )
        assert all(
            get_success_data(api.get_review_finding(finding["id"], AUDITOR))["status"]
            == "UNRESOLVED"
            for finding in findings
        )
        assert_fields(
            env.refresh(), verification_haircut_bps=1_500, latest_review_outcome="FAIL"
        )

    def test_level_two_reprices_every_asset_and_suspends_the_findings_bearer(self, api):
        """PRD §3.8: "**Level two — repricing the collateral.** Because the member's
        `verification_haircut_bps` changed, every collateral asset of that member whose
        `status` is `ELIGIBLE` or `SUSPENDED` has its `discount_factor_bps` and
        `lendable_value_cents` recomputed with the new haircut subtracted."

        Design: Difficulty/transitive_cascade/review_close_fail_cascades_five_levels_to_subsidy_release
        """
        env, _allocation_id, review, _findings, _before = self._member_at_the_moment_of_close(api)

        close_review(api, review["id"])

        assert_asset_valuation(read_asset(api, env.assets["sf"]["id"]), 6_300, 12_600_000)
        assert_asset_valuation(read_asset(api, env.assets["cre"]["id"]), 3_200, 15_360_000)
        assert_fields(
            read_asset(api, env.assets["heloc"]["id"]),
            status="SUSPENDED",
            discount_factor_bps=0,
            lendable_value_cents=0,
            ineligibility_reason="UNRESOLVED_REVIEW_FINDING",
        )

    def test_levels_three_and_four_freeze_the_member_and_size_the_cure(self, api):
        """PRD §3.8: "**Level three — resizing the member.** Because asset lendable
        values changed, `lendable_collateral_value_cents` and
        `borrowing_capacity_cents` are recomputed. When the recomputed
        `borrowing_capacity_cents` is negative, the member's `collateral_posture`
        becomes `FROZEN`."

        Design: Difficulty/transitive_cascade/review_close_fail_cascades_five_levels_to_subsidy_release
        """
        env, _allocation_id, review, _findings, _before = self._member_at_the_moment_of_close(api)

        close_review(api, review["id"])

        member = env.refresh()
        assert member["lendable_collateral_value_cents"] == 27_960_000
        assert member["collateral_posture"] == "FROZEN"
        assert_shortfall(
            member,
            "OPEN",
            5_140_000,
            shortfall_opened_at="2026-08-01T00:00:00.000Z",
            shortfall_cure_deadline="2026-08-06T00:00:00.000Z",
        )

    def test_level_four_cancels_the_pending_advances_and_shortfalls_the_funded_one(self, api):
        """PRD §3.8: "Every advance of the member whose `credit_status` is `FUNDED` and
        whose `collateral_status` is `SECURED` moves to `collateral_status`
        `SHORTFALL` — its `credit_status` is untouched, and the advance stays
        outstanding and interest-bearing. Every advance whose `credit_status` is
        `REQUESTED` or `CREDIT_APPROVED` moves to `credit_status`
        `CANCELLED_FOR_COLLATERAL`."

        Design: Difficulty/transitive_cascade/review_close_fail_cascades_five_levels_to_subsidy_release
        """
        env, _allocation_id, review, _findings, _before = self._member_at_the_moment_of_close(api)

        close_review(api, review["id"])

        assert_advance_dimensions(
            read_advance(api, env.advances["d"]["id"]), "FUNDED", "SHORTFALL"
        )
        for key in ("e", "f"):
            assert (
                read_advance(api, env.advances[key]["id"])["credit_status"]
                == "CANCELLED_FOR_COLLATERAL"
            )
        assert env.refresh()["committed_advances_cents"] == 0

    def test_level_five_releases_the_spill_before_the_take_and_reopens_the_pool(self, api):
        """PRD §3.8: "**Level five — unwinding what those cancellations committed.**
        Each cancelled advance carrying a `community_program_allocation_id` releases
        its committed subsidy back to the buckets it was charged to, reversing the
        commit exactly: the spill is returned to `bucket_committed_general_cents`
        first, then the purpose take is returned to the purpose bucket's committed
        figure."

        Design: Difficulty/transitive_cascade/review_close_fail_cascades_five_levels_to_subsidy_release
        """
        env, allocation_id, review, _findings, before = self._member_at_the_moment_of_close(api)
        assert_fields(
            before,
            bucket_committed_first_time_cents=140_000,
            bucket_committed_rehabilitation_cents=100_000,
            bucket_committed_general_cents=160_000,
            committed_cents=400_000,
            remaining_cents=0,
            status="CLOSED",
        )

        close_review(api, review["id"])

        assert_fields(
            _read_allocation(api, allocation_id),
            bucket_committed_first_time_cents=0,
            bucket_committed_rehabilitation_cents=0,
            bucket_committed_general_cents=0,
            committed_cents=0,
            remaining_cents=400_000,
            status="OPEN",
        )
        assert_stock_position(
            env.refresh(),
            required_activity_stock_cents=1_350_000,
            required_total_stock_cents=10_950_000,
            stock_deficiency_cents=0,
            excess_stock_cents=0,
        )


class TestFullPrepaymentCascade:
    """Settling a full prepayment: event, member cure, sibling advance restored."""

    def _frozen_member_with_a_quoted_prepayment(self, api):
        """Two funded advances, a failed review, and a quote taken on 2026-11-01."""
        pin_clock(api)
        set_market_rate(api, 300)
        env = member_with_eligible_sf(api)
        add_heloc(api, env)
        product = create_product(
            api,
            prepayment_fee_method="SYMMETRIC_MARKET_VALUE",
            symmetric_credit_enabled=False,
        )
        env.advances["d"] = funded_advance(
            api,
            env,
            product["id"],
            term_days=360,
            requested_net_proceeds_cents=13_370_000,
            fund_stock_from_advance=True,
        )
        env.advances["g"] = funded_advance(
            api,
            env,
            product["id"],
            term_days=1_000,
            requested_net_proceeds_cents=950_000,
            fund_stock_from_advance=True,
        )
        member_with_failed_review(api, env, env.assets["heloc"]["id"])
        pin_clock(api, "2026-11-01T00:00:00Z")
        event = quote_prepayment(api, env, env.advances["d"]["id"], 14_000_000, "FULL")
        pin_clock(api, "2026-11-03T00:00:00Z")
        set_market_rate(api, 250)
        return env, event

    def test_the_failed_review_leaves_both_advances_in_shortfall_before_settlement(self, api):
        """PRD §3.8: "**Level four — opening the shortfall and marking the advances.**
        Because the posture became `FROZEN`, `shortfall_status` moves `NONE → OPEN`,
        `shortfall_required_cure_cents` is sized as described in §3.9,
        `shortfall_opened_at` is stamped from the logical clock and
        `shortfall_cure_deadline` is set to that instant plus five days."

        Design: Difficulty/transitive_cascade/full_prepayment_settlement_cascades_three_levels_to_posture_restore
        """
        env, _event = self._frozen_member_with_a_quoted_prepayment(api)

        member = env.refresh()

        assert member["collateral_posture"] == "FROZEN"
        assert member["borrowing_capacity_cents"] == -2_400_000
        assert_shortfall(member, "OPEN", 2_700_000)
        for key in ("d", "g"):
            assert_advance_dimensions(
                read_advance(api, env.advances[key]["id"]), "FUNDED", "SHORTFALL"
            )

    def test_level_one_settles_the_event_prepays_the_advance_and_requests_redemption(self, api):
        """PRD §3.7: "**First**, the event moves to `SETTLED`, the advance's
        `outstanding_principal_cents` is set to 0, `credit_status` moves `FUNDED →
        PREPAID`, `collateral_status` moves to `RELEASED` from either `SECURED` or
        `SHORTFALL`, and the linked `ISSUED` `ACTIVITY` subscription of this advance
        moves to `REDEMPTION_REQUESTED`."

        Design: Difficulty/transitive_cascade/full_prepayment_settlement_cascades_three_levels_to_posture_restore
        """
        env, event = self._frozen_member_with_a_quoted_prepayment(api)

        settled = validate_success(
            api.settle_prepayment_event(event["id"], CREDIT_TWO)
        )

        assert_fields(
            settled,
            status="SETTLED",
            quoted_remaining_days=268,
            quoted_fee_cents=130_278,
            settled_remaining_days=266,
            admin_fee_cents=7_000,
            settled_fee_cents=188_028,
            fee_delta_cents=57_750,
        )
        advance = read_advance(api, env.advances["d"]["id"])
        assert_advance_dimensions(advance, "PREPAID", "RELEASED")
        assert advance["outstanding_principal_cents"] == 0
        rows = assert_total_count(
            api.list_stock_subscriptions(
                CREDIT_ONE, {"advance_id": env.advances["d"]["id"]}
            ),
            1,
        )
        assert_fields(
            rows[0],
            subscription_type="ACTIVITY",
            amount_cents=630_000,
            status="REDEMPTION_REQUESTED",
            redemption_requested_at="2026-11-03T00:00:00.000Z",
        )

    def test_level_two_recomputes_the_member_and_cures_the_shortfall(self, api):
        """PRD §3.7: "**Second**, because the outstanding principal changed, the
        member's `total_outstanding_advances_cents` and `borrowing_capacity_cents` are
        recomputed; if `shortfall_status` was `OPEN` and the recomputed capacity is 0
        or greater, the shortfall moves `OPEN → CURED` with
        `shortfall_required_cure_cents` set to 0."

        Design: Difficulty/transitive_cascade/full_prepayment_settlement_cascades_three_levels_to_posture_restore
        """
        env, event = self._frozen_member_with_a_quoted_prepayment(api)

        settle_prepayment(api, event["id"])

        member = env.refresh()
        assert_fields(
            member,
            total_outstanding_advances_cents=1_000_000,
            borrowing_capacity_cents=11_600_000,
        )
        assert_shortfall(member, "CURED", 0)
        assert_stock_position(
            member,
            required_activity_stock_cents=50_000,
            required_total_stock_cents=9_650_000,
            stock_held_cents=10_280_000,
            excess_stock_cents=630_000,
        )

    def test_level_three_restricts_the_member_and_restores_the_sibling_advance(self, api):
        """PRD §3.7: "**Third**, because the shortfall was cured,
        `collateral_posture` is re-derived out of `FROZEN`: it becomes `RESTRICTED`
        when the member's `latest_review_outcome` is `FAIL`, and `OPEN` otherwise; and
        every advance of that member whose `collateral_status` is `SHORTFALL` moves
        back to `SECURED`."

        Design: Difficulty/transitive_cascade/full_prepayment_settlement_cascades_three_levels_to_posture_restore
        """
        env, event = self._frozen_member_with_a_quoted_prepayment(api)

        settle_prepayment(api, event["id"])

        member = env.refresh()
        assert member["latest_review_outcome"] == "FAIL"
        assert member["collateral_posture"] == "RESTRICTED"
        assert_advance_dimensions(
            read_advance(api, env.advances["g"]["id"]), "FUNDED", "SECURED"
        )
