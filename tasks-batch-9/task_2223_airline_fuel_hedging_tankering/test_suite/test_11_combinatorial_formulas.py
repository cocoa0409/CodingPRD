"""Formulas whose parts do not decompose into independent factors.

The burn penalty runs four inputs through a hinge, so halving the uplift does
not halve the penalty. A mark-to-market report rounds each instrument before it
sums, so the total is not the rounded total. Margin scales each requirement by
an exposure that excludes it, so four identical-rate swaps produce four
different per-gallon rates.
"""

from test_helpers import (
    ERR_COUNTERPARTY_CREDIT_EXCEEDED,
    TREASURY,
    assert_counterparty_credit,
    assert_gallon_tenths,
    assert_instrument_ledgers,
    assert_instrument_status,
    assert_money,
    assert_mtm_totals,
    assert_planned_economics,
    assert_program_accounting,
    assert_program_coverage,
    fixtures as fx,
    validate_error,
)

#: The revision leg of the hinge scenario, matching the 210-minute narrowbody
#: baseline with a 45,000-lb payload ceiling.
HINGE_LEG = dict(flight_number="UA200", departure_date="2027-02-16")

DEALER_A = dict(
    counterparty_code="DLRA",
    legal_name="Dealer A Bank NA",
    credit_rating="A",
    credit_limit_usd=1000000.00,
)
DEALER_B = dict(
    counterparty_code="DLRB",
    legal_name="Dealer B Bank NA",
    credit_rating="A",
    credit_limit_usd=1000000.00,
)
DEALER_C = dict(
    counterparty_code="DLRC",
    legal_name="Dealer C Bank NA",
    credit_rating="AA",
    credit_limit_usd=1000000.00,
)

#: The three exact revaluations, each ending in a half cent.
ROUNDED_MTM_VALUES = [1481665.19, 163005.71, 73581.43]
#: What summing the exact values and rounding once at the end would have given.
SUM_THEN_ROUND_TOTAL = 1718252.32


class TestBurnPenaltyPayloadHinge:
    @staticmethod
    def _directive_sent_back_for_revision(api):
        ctx = fx.setup_proposed_directive(
            api,
            3000,
            policy_overrides=dict(policy_code="FY27-CF1"),
            leg_overrides=HINGE_LEG,
        )
        ctx["proposed"] = ctx["directive"]
        ctx["directive"] = fx.do_request_directive_revision(
            api, ctx["directive"]["id"], "Trim the uplift, payload is tight."
        )
        return ctx

    def test_a_loaded_aircraft_carries_the_hinge_penalty_on_the_first_pass(self, api):
        """PRD §3.8: "First, the payload ratio is `payload_lbs` plus the uplift
        converted to pounds at 6.7 pounds per gallon, all divided by
        `max_takeoff_payload_lbs`, rounded to four decimal places."

        PRD §3.8: "Fourth and last, the raw carriage burn is multiplied by the
        penalty multiplier and the product is rounded to one tenth of a gallon."

        Three thousand gallons is 20,100 pounds on top of a 22,000-pound payload,
        which is 0.9356 of the 45,000-pound ceiling — well past the hinge — so the
        raw 315.0-gallon carriage burn is lifted to 368.9.

        Design: Difficulty/combinatorial_formula/tankering_burn_penalty_payload_hinge_four_inputs
        """
        ctx = self._directive_sent_back_for_revision(api)

        assert ctx["proposed"]["requested_uplift_gallons"] == 3000
        assert_planned_economics(
            ctx["proposed"],
            planned_burn_penalty_gallons=368.9,
            planned_gross_savings_usd=1890.00,
            planned_penalty_cost_usd=911.18,
            planned_net_savings_usd=978.82,
        )
        assert ctx["directive"]["status"] == "NEEDS_REVISION"

    def test_a_five_hundred_gallon_revision_leaves_the_multiplier_at_exactly_one(
        self, api
    ):
        """PRD §3.8: "A `FuelAnalyst` may then revise it, which advances
        `NEEDS_REVISION → PROPOSED`, overwrites `requested_uplift_gallons` with
        the new request value, re-runs the planned-basis burn penalty and savings
        against the *live* contracts so a contract change between passes is picked
        up, increments `revision_count` by one and increments the directive's
        `version` by one."

        Five hundred gallons is 3,350 pounds, so the payload ratio is 0.5633 and
        the excess over the 0.85 hinge is zero: the penalty is the bare
        52.5-gallon carriage burn, the gross saving 315.00, the penalty cost
        129.68 and the net 185.32.

        Design: Difficulty/combinatorial_formula/tankering_burn_penalty_payload_hinge_four_inputs
        """
        ctx = self._directive_sent_back_for_revision(api)

        revised = fx.do_revise_directive(api, ctx["directive"]["id"], 500)

        assert revised["status"] == "PROPOSED"
        assert revised["revision_count"] == 1
        assert revised["requested_uplift_gallons"] == 500
        assert_planned_economics(
            revised,
            planned_burn_penalty_gallons=52.5,
            planned_gross_savings_usd=315.00,
            planned_penalty_cost_usd=129.68,
            planned_net_savings_usd=185.32,
        )

    def test_the_penalty_falls_faster_than_the_uplift_because_of_the_hinge(self, api):
        """PRD §3.8: "The burn penalty is the heart of the tankering economics,
        and four inputs interact in it: the uplift, the fleet, the block time and
        the payload ratio, which enters through a hinge."

        Same leg, same fleet factor, same 210-minute block: only the uplift
        changed, by a factor of six, yet the penalty fell by a factor of just over
        seven, because the multiplier fell from 1.1712 to 1.0000 at the same time.

        Design: Difficulty/combinatorial_formula/tankering_burn_penalty_payload_hinge_four_inputs
        """
        ctx = self._directive_sent_back_for_revision(api)
        before = ctx["proposed"]["planned_burn_penalty_gallons"]

        revised = fx.do_revise_directive(api, ctx["directive"]["id"], 500)
        after = revised["planned_burn_penalty_gallons"]

        assert_gallon_tenths(before, 368.9, "planned_burn_penalty_gallons")
        assert_gallon_tenths(after, 52.5, "planned_burn_penalty_gallons")
        assert before / after > 3000 / 500


class TestMarkToMarketRoundThenSum:
    @staticmethod
    def _three_executed_instruments_and_an_open_run(api):
        """A swap, a collar and a call option, each facing a different dealer,
        chosen so that every exact revaluation lands on a half cent."""
        ctx = fx.setup_sized_program(
            api,
            policy_overrides=dict(
                policy_code="FY27-CF2", max_earnings_volatility_usd=500000.00
            ),
            counterparty_overrides=DEALER_A,
            program_overrides=dict(program_code="HP-CF2", target_coverage_pct=40.00),
        )
        program_id = ctx["program"]["id"]
        ctx["dealer_b"] = fx.do_create_counterparty(api, **DEALER_B)
        ctx["dealer_c"] = fx.do_create_counterparty(api, **DEALER_C)

        ctx["swap"] = fx.do_propose_swap(
            api,
            program_id,
            ctx["counterparty"]["id"],
            notional_gallons=3333330,
            strike_usd_per_gal=2.4055,
            maturity_month="2027-03",
        )
        ctx["collar"] = fx.do_propose_collar(
            api,
            program_id,
            ctx["dealer_b"]["id"],
            notional_gallons=1111150,
            cap_strike_usd_per_gal=2.7033,
            floor_strike_usd_per_gal=2.1000,
            maturity_month="2027-03",
        )
        ctx["option"] = fx.do_propose_call_option(
            api,
            program_id,
            ctx["dealer_c"]["id"],
            notional_gallons=777750,
            strike_usd_per_gal=2.6011,
            premium_usd=120000.55,
            maturity_month="2027-03",
        )
        fx.do_submit_program(api, program_id)
        fx.do_activate_program(api, program_id)

        for key in ("swap", "collar", "option"):
            ctx[key] = fx.do_execute_instrument(api, ctx[key]["id"])
        fx.do_designate_instrument(api, ctx["swap"]["id"])
        fx.do_designate_instrument(api, ctx["option"]["id"])

        ctx["run"] = fx.do_open_mtm_run(api, "2027-02", 2.8500)
        return ctx

    def test_each_instrument_is_rounded_to_cents_before_anything_is_summed(self, api):
        """PRD §3.7: "The rounding order is pinned: each instrument's exact value
        is rounded to two decimal places and written to its `mtm_value_usd`
        *first*, and only the already-rounded values are then summed."

        The swap's exact value is 1,481,665.1850, the collar's 163,005.7050 and
        the option's 73,581.4250 — three half cents, each of which must be on the
        instrument row before the report adds anything up.

        Design: Difficulty/combinatorial_formula/mtm_totals_round_per_instrument_then_sum
        """
        ctx = self._three_executed_instruments_and_an_open_run(api)

        fx.do_compute_mtm_run(api, ctx["run"]["id"])

        assert_instrument_ledgers(
            fx.read_instrument(api, ctx["swap"]["id"]), mtm_value_usd=1481665.19
        )
        assert_instrument_ledgers(
            fx.read_instrument(api, ctx["collar"]["id"]), mtm_value_usd=163005.71
        )
        assert_instrument_ledgers(
            fx.read_instrument(api, ctx["option"]["id"]), mtm_value_usd=73581.43
        )

    def test_the_report_total_is_the_sum_of_the_rounded_values(self, api):
        """PRD §3.7: "Summing exact values and rounding once at the end is wrong
        and can differ by whole cents on a three-trade portfolio."

        PRD §3.7: "`total_mtm_usd` is the sum of the rounded per-instrument
        values, `designated_mtm_usd` the sum over those whose `accounting_status`
        is `DESIGNATED`, and `undesignated_mtm_usd` the sum over those whose
        `accounting_status` is `UNDESIGNATED` or `DEDESIGNATED`; each total is
        rounded to two decimal places, which is a no-op over already-rounded
        inputs."

        Round-then-sum gives 1,718,252.33; sum-then-round would have given
        1,718,252.32, one cent lower.

        Design: Difficulty/combinatorial_formula/mtm_totals_round_per_instrument_then_sum
        """
        ctx = self._three_executed_instruments_and_an_open_run(api)

        computed = fx.do_compute_mtm_run(api, ctx["run"]["id"])

        assert_mtm_totals(
            computed,
            status="COMPUTED",
            instrument_count=3,
            total_mtm_usd=1718252.33,
        )
        assert_money(computed["total_mtm_usd"], sum(ROUNDED_MTM_VALUES), "total_mtm_usd")
        assert round(computed["total_mtm_usd"], 2) != SUM_THEN_ROUND_TOTAL

    def test_the_two_accounting_buckets_partition_the_scope(self, api):
        """PRD §3.7: "The two accounting buckets partition the scope, so the
        designated and undesignated totals always add up to `total_mtm_usd`."

        PRD §3.7: "Computing sets `computed_at` from the logical clock, increments
        the run's `version` by one and increments each touched instrument's
        `version` by one — and touches nothing else. It deliberately does not move
        a programme, a counterparty or a collateral row."

        The designated swap and option carry 1,555,246.62 between them and the
        undesignated collar 163,005.71, while the programme's own accounting
        ledgers stay at zero because only publication moves them.

        Design: Difficulty/combinatorial_formula/mtm_totals_round_per_instrument_then_sum
        """
        ctx = self._three_executed_instruments_and_an_open_run(api)

        computed = fx.do_compute_mtm_run(api, ctx["run"]["id"])

        assert_mtm_totals(
            computed,
            designated_mtm_usd=1555246.62,
            undesignated_mtm_usd=163005.71,
            total_mtm_usd=1718252.33,
        )
        assert_money(
            computed["designated_mtm_usd"] + computed["undesignated_mtm_usd"],
            computed["total_mtm_usd"],
            "designated plus undesignated",
        )

        program = fx.read_program(api, ctx["program"]["id"])
        assert_program_accounting(
            program,
            designated_mtm_usd=0.00,
            undesignated_mtm_usd=0.00,
            earnings_volatility_usd=0.00,
            compliance_posture="COMPLIANT",
        )


class TestMarginConcentrationAddOnLadder:
    @staticmethod
    def _four_proposed_swaps_against_a_three_hundred_thousand_limit(api):
        ctx = fx.setup_sized_program(
            api,
            policy_overrides=dict(
                policy_code="FY27-CF3", max_earnings_volatility_usd=500000.00
            ),
            counterparty_overrides=dict(
                counterparty_code="DLRA",
                legal_name="Dealer A Bank NA",
                credit_rating="A",
                credit_limit_usd=300000.00,
            ),
            program_overrides=dict(program_code="HP-CF3", target_coverage_pct=43.00),
        )
        program_id = ctx["program"]["id"]
        counterparty_id = ctx["counterparty"]["id"]
        ctx["swaps"] = [
            fx.do_propose_swap(
                api,
                program_id,
                counterparty_id,
                notional_gallons=notional,
                strike_usd_per_gal=strike,
                maturity_month="2027-03",
            )
            for notional, strike in (
                (3000000, 2.4000),
                (1000000, 2.4100),
                (500000, 2.4200),
                (200000, 2.4300),
            )
        ]
        fx.do_submit_program(api, program_id)
        ctx["program"] = fx.do_activate_program(api, program_id)
        return ctx

    def test_each_requirement_is_scaled_by_the_exposure_that_excludes_it(self, api):
        """PRD §3.4: "Step three converts that pre-add-on exposure into a
        concentration percentage: divided by the counterparty's
        `credit_limit_usd`, multiplied by 100 and rounded to two decimal places.
        Step four selects an add-on rate from that rounded percentage, with lower
        bounds inclusive: 0.00 below 50 percent, 0.10 from 50 up to but not
        including 75 percent, 0.25 from 75 up to but not including 90 percent, and
        0.50 at 90 percent or above."

        The first trade sees an empty book and pays its bare 180,000.00; the
        second sees 60.00 percent concentration and pays 66,000.00 on a 60,000.00
        base; the third sees 82.00 percent and pays 37,500.00 on a 30,000.00 base.

        Design: Difficulty/combinatorial_formula/margin_concentration_addon_tier_ladder
        """
        ctx = self._four_proposed_swaps_against_a_three_hundred_thousand_limit(api)

        first = fx.do_execute_instrument(api, ctx["swaps"][0]["id"])
        second = fx.do_execute_instrument(api, ctx["swaps"][1]["id"])
        third = fx.do_execute_instrument(api, ctx["swaps"][2]["id"])

        assert_instrument_ledgers(first, margin_requirement_usd=180000.00)
        assert_instrument_ledgers(second, margin_requirement_usd=66000.00)
        assert_instrument_ledgers(third, margin_requirement_usd=37500.00)

    def test_the_same_per_gallon_rate_yields_three_different_effective_rates(self, api):
        """PRD §3.4: "Step one computes a base margin that does not depend on
        exposure at all: `notional_gallons` multiplied by a per-gallon margin rate
        that is 0.06 for a `SWAP`, 0.04 for a `COLLAR` and 0.02 for a
        `CALL_OPTION`, plus — only when the instrument's `mtm_value_usd` is
        negative — the absolute size of that negative mark-to-market multiplied by
        an adverse-mark factor of 1.10; a zero or positive `mtm_value_usd`
        contributes nothing."

        PRD §3.4: "Step six advances the counterparty ledger — and only then, so
        that the *next* instrument's step three sees this requirement."

        Three swaps at one declared rate come out at 0.0600, 0.0660 and 0.0750
        dollars per gallon, in that order, purely because each one moved the
        exposure the next one reads.

        Design: Difficulty/combinatorial_formula/margin_concentration_addon_tier_ladder
        """
        ctx = self._four_proposed_swaps_against_a_three_hundred_thousand_limit(api)

        rates = []
        for swap in ctx["swaps"][:3]:
            executed = fx.do_execute_instrument(api, swap["id"])
            rates.append(
                round(
                    executed["margin_requirement_usd"] / executed["notional_gallons"], 4
                )
            )

        assert rates == [0.0600, 0.0660, 0.0750]
        assert_counterparty_credit(
            fx.read_counterparty(api, ctx["counterparty"]["id"]),
            utilized_credit_usd=283500.00,
            utilization_pct=94.50,
            credit_posture="CONSTRAINED",
        )

    def test_the_fourth_execution_is_refused_and_leaves_the_ladder_where_it_was(
        self, api
    ):
        """PRD §3.4: "Finally, the counterparty's `utilized_credit_usd` plus this
        trade's freshly computed `margin_requirement_usd` must be no greater than
        its `credit_limit_usd`, otherwise `ERR_COUNTERPARTY_CREDIT_EXCEEDED`."

        PRD §3.1: "from 90 percent up to but not including 100 percent it is
        `CONSTRAINED`; and at 100 percent or above it is `BREACH`."

        A 200,000-gallon swap has a 12,000.00 base, but the 94.50 percent
        concentration selects the 0.50 add-on and turns it into 18,000.00, which
        takes the book to 301,500.00 against a 300,000.00 limit. Nothing is
        written: the trade stays `PROPOSED` with no requirement and the dealer
        stays at 283,500.00 and `CONSTRAINED`, one tier short of `BREACH`.

        Design: Difficulty/combinatorial_formula/margin_concentration_addon_tier_ladder
        """
        ctx = self._four_proposed_swaps_against_a_three_hundred_thousand_limit(api)
        for swap in ctx["swaps"][:3]:
            fx.do_execute_instrument(api, swap["id"])

        fourth_id = ctx["swaps"][3]["id"]
        validate_error(
            api.execute_hedge_instrument(fourth_id, headers=TREASURY),
            ERR_COUNTERPARTY_CREDIT_EXCEEDED,
            422,
        )

        fourth = fx.read_instrument(api, fourth_id)
        assert_instrument_status(fourth, trade_status="PROPOSED")
        assert_instrument_ledgers(fourth, margin_requirement_usd=0)

        counterparty = fx.read_counterparty(api, ctx["counterparty"]["id"])
        assert_counterparty_credit(
            counterparty,
            utilized_credit_usd=283500.00,
            utilization_pct=94.50,
            credit_posture="CONSTRAINED",
        )

        assert_program_coverage(
            fx.read_program(api, ctx["program"]["id"]),
            hedged_gallons=4500000,
            coverage_pct_delta=40.91,
        )
