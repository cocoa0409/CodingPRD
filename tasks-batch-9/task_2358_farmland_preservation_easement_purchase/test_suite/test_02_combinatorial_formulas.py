"""The funding waterfall and the administrative-fee tier.

Both calculations chain several independent decisions, and each intermediate
rounding or selection step has a natural-looking wrong variant.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import (
    TEST_USERS,
    api_client,
    assert_cost_stack,
    commitment_on,
    commitments_of,
    issue_offer,
    read_source,
    setup_funded_application,
    setup_ranked_application,
)

ADMIN = TEST_USERS["program_admin_headers"]


class TestFundingWaterfall:
    """Per-source floors, then LAST_NON_ZERO_TAKE for the surviving remainder."""

    def test_each_share_cap_is_floored_independently_before_summing(self):
        """Three independently floored caps leave the walk one cent short.

        PRD §3.6: "At each source, compute a share cap by multiplying the target
        total by that source's `max_share_pct` and flooring to whole cents."

        Design: Difficulty/combinatorial_formula/funding_waterfall_per_source_floor_then_remainder_to_last_non_zero_take
        """
        scenario = setup_funded_application()
        plan = scenario["plan_result"]
        assert plan["funded_cost_cents"] == 160_364_925
        assert plan["commitment_count"] == 3

        # floor(160,364,925 x 0.35) = 56,127,723 (the un-floored share is .75)
        assert plan["local_total_cents"] == 56_127_723
        # floor(160,364,925 x 0.40) = 64,145,970 exactly
        assert plan["state_total_cents"] == 64_145_970
        # floor(160,364,925 x 0.25) = 40,091,231 (the un-floored share is .25),
        # plus the one absorbed cent
        assert plan["federal_total_cents"] == 40_091_232
        assert (
            plan["local_total_cents"]
            + plan["state_total_cents"]
            + plan["federal_total_cents"]
            == 160_364_925
        )

    def test_the_surviving_remainder_lands_on_the_last_non_zero_take(self):
        """The one-cent residue is absorbed by the final source in the sweep.

        PRD §3.6: "If a remainder survives the walk and at least one source took
        a non-zero amount, the last source with a non-zero take absorbs an extra
        amount equal to the smaller of the surviving remainder and that source's
        still-unused headroom (its `available_cents` less what it has already
        taken)."

        Design: Difficulty/combinatorial_formula/funding_waterfall_per_source_floor_then_remainder_to_last_non_zero_take
        """
        scenario = setup_funded_application()
        assert scenario["plan_result"]["remainder_absorbed_cents"] == 1

        application_id = scenario["application"]["id"]
        sources = scenario["sources"]
        local = commitment_on(application_id, sources["local"]["id"])
        state = commitment_on(application_id, sources["state"]["id"])
        federal = commitment_on(application_id, sources["federal"]["id"])

        assert (local["sweep_order"], state["sweep_order"], federal["sweep_order"]) == (
            1,
            2,
            3,
        )
        # `absorbed_remainder_cents` is 0 on every other commitment.
        assert local["absorbed_remainder_cents"] == 0
        assert state["absorbed_remainder_cents"] == 0
        assert federal["absorbed_remainder_cents"] == 1
        assert local["amount_cents"] == 56_127_723
        assert state["amount_cents"] == 64_145_970
        assert federal["amount_cents"] == 40_091_232

    def test_the_absorbing_source_is_not_re_checked_against_its_own_share_cap(self):
        """The absorbed cent pushes federal past its own floored cap, legally.

        PRD §3.6: "The absorbing source's own `max_share_pct` is deliberately
        not re-checked against the absorbed remainder; only the program-level
        federal ceiling still binds."

        Design: Difficulty/combinatorial_formula/funding_waterfall_per_source_floor_then_remainder_to_last_non_zero_take
        """
        scenario = setup_funded_application()
        federal_commitment = commitment_on(
            scenario["application"]["id"], scenario["sources"]["federal"]["id"]
        )
        # Its own floored share cap was 40,091,231.
        assert federal_commitment["amount_cents"] == 40_091_232
        # The program-level federal ceiling is floor(160,364,925 x 0.50).
        assert federal_commitment["amount_cents"] <= 80_182_462

    def test_every_commitment_freezes_its_source_obligation_window(self):
        """Each commitment carries a frozen copy of the source's window.

        PRD §3.6: "Each new `FundingCommitment` records its `application_id`,
        its `funding_source_id`, its strictly positive `amount_cents`, its
        `sweep_order`, its `absorbed_remainder_cents`, and a frozen copy of the
        source's obligation window as `window_start` and `window_end` for later
        capacity reasoning."

        Design: Difficulty/combinatorial_formula/funding_waterfall_per_source_floor_then_remainder_to_last_non_zero_take
        """
        scenario = setup_funded_application()
        for commitment in commitments_of(scenario["application"]["id"]):
            source = read_source(commitment["funding_source_id"])
            assert commitment["window_start"] == source["obligation_window_start"]
            assert commitment["window_end"] == source["obligation_window_end"]
            assert commitment["status"] == "RESERVED"
            assert commitment["lapse_reason"] is None


class TestAdminFeeTierBasis:
    """The tier is selected on the pre-fee cash portion, never on the total."""

    def test_tier_is_chosen_on_the_pre_fee_price_not_on_the_total(self):
        """A price under 75,000,000 whose total crosses it still pays 2 percent.

        PRD §3.5: "The tier is chosen on the pre-fee cash portion and never on
        the total; choosing it on the total is the natural-looking wrong variant
        and produces a different fee whenever the total crosses a tier boundary
        that the pre-fee price does not."

        Design: Difficulty/combinatorial_formula/admin_fee_tier_selected_on_pre_fee_bargain_sale_price_not_on_total
        """
        scenario = setup_ranked_application()
        validate_success(api_client.set_clock("2026-10-05T00:00:00Z"))
        application = issue_offer(
            scenario["application"]["id"], 74_500_000, "FULL_PURCHASE"
        )

        assert application["donation_cents"] == 0
        assert application["bargain_sale_price_cents"] == 74_500_000
        # 74,500,000 is strictly below 75,000,000, so the rate is 0.020.
        assert application["admin_fee_cents"] == 1_490_000
        assert application["total_program_cost_cents"] == 75_990_000
        # The total-basis variant would have selected 0.015 and charged
        # 1,117,500 for a total of 75,617,500.
        assert application["admin_fee_cents"] != 1_117_500
        assert_cost_stack(application)

    def test_the_donation_pulls_the_pre_fee_price_down_into_a_cheaper_tier(self):
        """A large donation moves the tier even though the offer does not.

        PRD §3.5: "Third, select the administrative fee rate on that pre-fee cash
        portion: a rate of 0.030 — three percent — when
        `bargain_sale_price_cents` is strictly below 25,000,000 cents, otherwise
        a rate of 0.020 when it is strictly below 75,000,000 cents, otherwise a
        rate of 0.015."

        Design: Difficulty/combinatorial_formula/admin_fee_tier_selected_on_pre_fee_bargain_sale_price_not_on_total
        """
        scenario = setup_ranked_application()
        validate_success(api_client.set_clock("2026-10-05T00:00:00Z"))
        application = issue_offer(
            scenario["application"]["id"],
            100_000_000,
            "BARGAIN_SALE",
            donation_pct=0.30,
        )

        assert application["donation_cents"] == 30_000_000
        assert application["bargain_sale_price_cents"] == 70_000_000
        # 70,000,000 is strictly below 75,000,000, so the rate is 0.020 even
        # though the 100,000,000 negotiated amount is not.
        assert application["admin_fee_cents"] == 1_400_000
        assert application["total_program_cost_cents"] == 71_400_000
        assert application["admin_fee_cents"] != 1_050_000
        assert_cost_stack(application)

    def test_the_donation_rounds_half_up_before_the_tier_is_selected(self):
        """Two rounding steps in order: donation first, then the fee.

        PRD §3.5: "There are exactly two rounding steps, in the stated order:
        donation first, administrative fee second."

        Design: Difficulty/combinatorial_formula/admin_fee_tier_selected_on_pre_fee_bargain_sale_price_not_on_total
        """
        scenario = setup_ranked_application()
        validate_success(api_client.set_clock("2026-10-05T00:00:00Z"))
        application = issue_offer(
            scenario["application"]["id"], 50_000_001, "BARGAIN_SALE", donation_pct=0.5
        )

        # 50,000,001 x 0.5 is 25,000,000.5, which rounds half up to 25,000,001.
        assert application["donation_cents"] == 25_000_001
        assert application["bargain_sale_price_cents"] == 25_000_000
        # 25,000,000 is not strictly below 25,000,000, so the rate is 0.020.
        assert application["admin_fee_cents"] == 500_000
        assert application["total_program_cost_cents"] == 25_500_000
        # Truncating the donation instead would have left a pre-fee price of
        # 25,000,001 and a total of 25,500,001.
        assert application["total_program_cost_cents"] != 25_500_001
        assert_cost_stack(application)
