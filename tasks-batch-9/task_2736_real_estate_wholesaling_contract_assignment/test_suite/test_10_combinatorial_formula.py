"""
Multi-input formulas whose composition order is observable: the settlement
split that rounds per component before subtracting, and the lender fee tier
selected from the grossed-up base rather than the raw purchase price.
"""

from test_helpers import (
    assert_assignment_agreement,
    assert_assignment_offer,
    assert_deal_analysis,
    assert_nulls,
    assert_purchase_contract,
    assert_settlement_arithmetic,
    build_executed_agreement,
    build_signed_contract,
    elect,
    factories,
    make_wholesaler_headers,
    read_agreement,
    read_contract,
    read_offer,
    settle_agreement,
    validate_success,
    TIER_2_MIN_FEE_CENTS,
    TITLE_AGENT_1,
)

CONTRACT_TERMS = {
    "purchase_price_cents": 18000000,
    "earnest_money_cents": 500000,
    "inspection_period_days": 7,
}


def _settled_agreement(api):
    """An assignment fee of exactly 1500010 cents, carried through settlement."""
    scenario = build_executed_agreement(
        api,
        clock="2026-08-10T00:00:00Z",
        buyer_price_cents=19500010,
        buyer_deposit_cents=1000000,
        structure_election="ASSIGNMENT_ELECTED",
        contract_kwargs=dict(CONTRACT_TERMS),
    )
    assert_assignment_agreement(
        scenario.agreement,
        settlement_status="PENDING_SETTLEMENT",
        assignment_fee_cents=1500010,
        title_holdback_cents=0,
        state_transfer_surcharge_cents=0,
        marketing_cost_recovery_cents=0,
        wholesaler_net_cents=0,
    )
    settled = settle_agreement(api, scenario.agreement_id, TITLE_AGENT_1)
    return scenario, settled


class TestSettlementSplitRoundsPerComponent:
    """Three rates on one fee, each product rounded on its own."""

    def test_each_of_the_three_deductions_is_rounded_before_any_subtraction(self, api):
        """
        "`title_holdback_cents` is three and a quarter percent of
        `assignment_fee_cents`; `state_transfer_surcharge_cents` is
        three-quarters of one percent of it; `marketing_cost_recovery_cents` is
        one and fifty-five hundredths percent of it. **Each of those three
        products is rounded half up to a whole cent on its own, before any of
        them is subtracted.**"

        "Collapsing the three rates into a single five and fifty-five hundredths
        percent rate and rounding once produces a different, wrong answer on fee
        amounts whose fractional cents straddle the half."

        Design: Difficulty/combinatorial_formula/assignment_fee_settlement_rounds_per_component_then_sums
        """
        scenario, settled = _settled_agreement(api)

        # 1500010 x 0.0325 = 48750.325, x 0.0075 = 11250.075,
        # x 0.0155 = 23250.155 — every fractional part rounds down on its own.
        assert_assignment_agreement(
            settled,
            assignment_fee_cents=1500010,
            title_holdback_cents=48750,
            state_transfer_surcharge_cents=11250,
            marketing_cost_recovery_cents=23250,
        )
        deductions = (
            settled["title_holdback_cents"]
            + settled["state_transfer_surcharge_cents"]
            + settled["marketing_cost_recovery_cents"]
        )
        assert deductions == 83250, (
            "the three separately rounded products must total 83250 cents, "
            f"got {deductions}"
        )
        assert deductions != 83251, (
            "83251 is what a single 0.0555 rate rounded once would produce, and "
            "the split is emphatically not computed that way"
        )
        assert_settlement_arithmetic(settled)
        assert_assignment_agreement(
            read_agreement(api, scenario.agreement_id, scenario.w_id),
            title_holdback_cents=48750,
            state_transfer_surcharge_cents=11250,
            marketing_cost_recovery_cents=23250,
        )

    def test_residual_net_is_one_cent_above_the_collapsed_rate_answer(self, api):
        """
        "`wholesaler_net_cents` is then `assignment_fee_cents` less the three
        rounded components."

        "**Settlement.** A title agent settles the agreement by supplying a
        `settlement_reference`, which drives `PENDING_SETTLEMENT → SETTLED` and
        stamps `settled_at`."

        "It drives the offer from `ACCEPTED` to `CONSUMED`, drives the contract's
        `assignment_status` from `MARKETED` to `ASSIGNED`, recomputes
        `double_close_spread_cents` where the contract elected a double close,
        and increments the wholesaler's `executed_assignment_count`."

        Design: Difficulty/combinatorial_formula/assignment_fee_settlement_rounds_per_component_then_sums
        """
        scenario, settled = _settled_agreement(api)

        # 1500010 - 83250 == 1416760; collapsing the rates would leave 1416759.
        assert_assignment_agreement(
            settled,
            settlement_status="SETTLED",
            wholesaler_net_cents=1416760,
            settlement_reference="STL-2026-000117",
            settled_at="2026-08-10T00:00:00Z",
        )
        assert settled["wholesaler_net_cents"] != 1416759, (
            "1416759 is the residual left by rounding 1500010 x 0.0555 once; "
            "the per-component order must leave one cent more"
        )
        assert_assignment_offer(
            read_offer(api, scenario.offer_id, scenario.w_id), status="CONSUMED"
        )
        assert_purchase_contract(
            read_contract(api, scenario.pc_id, scenario.w_id),
            assignment_status="ASSIGNED",
        )


class TestLenderFeeTierKeyedOnTheGrossedUpBase:
    """A purchase price under the tier edge whose base is over it."""

    def test_gross_up_lifts_the_base_into_the_second_tier(self, api):
        """
        "Step one grosses up the purchase price with closing and recording
        costs: `funding_base_cents` is `purchase_price_cents` plus two point one
        percent of `purchase_price_cents`, that percentage product rounded half
        up to a whole cent before it is added."

        "Step two selects the transactional lender's fee tier **from the
        grossed-up base**, never from the raw purchase price and never from the
        final total — this is the single most commonly mis-implemented part of
        the schedule, and it means a contract whose purchase price sits just
        under a tier edge is nevertheless priced in the next tier up."

        "A base from fifteen million cents up to but not including thirty
        million cents (three hundred thousand dollars) sits in the second tier,
        at two and a quarter percent with a minimum fee of forty-five thousand
        cents."

        Design: Difficulty/combinatorial_formula/double_close_lender_fee_tier_keyed_on_funding_base_not_purchase_price
        """
        scenario = build_signed_contract(
            api,
            clock="2026-08-10T00:00:00Z",
            contract_kwargs={
                "purchase_price_cents": 14800000,
                "earnest_money_cents": 500000,
                "inspection_period_days": 7,
            },
        )
        assert_deal_analysis(scenario.analysis, max_allowable_offer_cents=20500000)

        elected = elect(api, scenario.pc_id, scenario.w_id, "DOUBLE_CLOSE_ELECTED")

        # 14800000 x 0.021 == 310800 exactly, so the base is 15110800 — over the
        # fifteen-million edge even though the price itself is under it.
        assert_purchase_contract(
            elected,
            structure_election="DOUBLE_CLOSE_ELECTED",
            purchase_price_cents=14800000,
            funding_base_cents=15110800,
            transactional_lender_fee_cents=339993,
            total_funding_required_cents=15450793,
        )
        assert elected["transactional_lender_fee_cents"] != 453324, (
            "453324 is the tier-one three percent rate on the same base; the "
            "tier must be chosen from the base, which sits in tier two"
        )
        assert elected["total_funding_required_cents"] != 15564124, (
            "15564124 is the total a tier-one fee would produce"
        )
        assert elected["transactional_lender_fee_cents"] > TIER_2_MIN_FEE_CENTS, (
            "the tier-two minimum of 45000 cents must not bind here: "
            f"{elected['transactional_lender_fee_cents']}"
        )

    def test_election_writes_the_schedule_and_leaves_the_other_dimensions(self, api):
        """
        "Step three applies the tier: `transactional_lender_fee_cents` is the
        greater of that tier's minimum fee and the base multiplied by the tier
        rate, the product rounded half up to a whole cent **before** the
        minimum-fee floor is applied. Step four totals:
        `total_funding_required_cents` is `funding_base_cents` plus
        `transactional_lender_fee_cents`."

        "Step five is the spread, and it stays null until an offer on this
        contract reaches `ACCEPTED`: `double_close_spread_cents` is the accepted
        offer's `buyer_price_cents` less `total_funding_required_cents`."

        Design: Difficulty/combinatorial_formula/double_close_lender_fee_tier_keyed_on_funding_base_not_purchase_price
        """
        scenario = build_signed_contract(
            api,
            clock="2026-08-10T00:00:00Z",
            contract_kwargs={
                "purchase_price_cents": 14800000,
                "earnest_money_cents": 500000,
                "inspection_period_days": 7,
            },
        )
        assert_purchase_contract(
            scenario.contract,
            contract_status="SIGNED",
            structure_election="UNDECIDED",
            assignment_status="NOT_MARKETED",
        )
        assert_nulls(
            scenario.contract,
            "funding_base_cents",
            "transactional_lender_fee_cents",
            "total_funding_required_cents",
            "double_close_spread_cents",
            label="purchase_contract",
        )

        response = api.elect_structure(
            scenario.pc_id,
            factories.elect_structure_payload("DOUBLE_CLOSE_ELECTED"),
            make_wholesaler_headers(scenario.w_id),
        )
        validate_success(response, 200)

        persisted = read_contract(api, scenario.pc_id, scenario.w_id)
        assert_purchase_contract(
            persisted,
            funding_base_cents=15110800,
            transactional_lender_fee_cents=339993,
            total_funding_required_cents=15450793,
            double_close_spread_cents=None,
            contract_status="SIGNED",
            assignment_status="NOT_MARKETED",
        )
        assert (
            persisted["funding_base_cents"]
            + persisted["transactional_lender_fee_cents"]
            == persisted["total_funding_required_cents"]
        ), f"step four is a plain sum of steps one and three: {persisted}"
