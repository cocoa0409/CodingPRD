"""Three quantities that are each computed twice, on two different bases.

Coverage is reported on a notional basis and a delta-adjusted basis from the
same executed book; tankering economics are computed on a planned basis at
creation and on a reconciled basis against flown data; effectiveness is
measured for the period and cumulatively since designation. In each pair the
two variants deliberately disagree, and in each pair only one of them is the
one the server acts on.
"""

from test_helpers import (
    assert_effectiveness_outcome,
    assert_gallon_tenths,
    assert_instrument_ledgers,
    assert_instrument_status,
    assert_money,
    assert_pct,
    assert_pinned_prices,
    assert_planned_economics,
    assert_program_coverage,
    assert_reconciled_economics,
    assert_whole_gallons,
    fixtures as fx,
)

#: The two dealers of the two-instrument book, each with head-room to spare.
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


class TestCoverageOnTwoBases:
    @staticmethod
    def _book_of_one_swap_and_one_collar(api):
        """A programme sized to 11,000,000 gallons carrying a 3,000,000-gallon
        swap facing one dealer and a 2,000,000-gallon collar facing another,
        both still `PROPOSED`."""
        ctx = fx.setup_sized_program(
            api,
            policy_overrides=dict(policy_code="FY27-DV1"),
            counterparty_overrides=DEALER_A,
            program_overrides=dict(program_code="HP-DV1", target_coverage_pct=45.00),
        )
        program_id = ctx["program"]["id"]
        ctx["dealer_b"] = fx.do_create_counterparty(api, **DEALER_B)
        ctx["swap"] = fx.do_propose_swap(
            api,
            program_id,
            ctx["counterparty"]["id"],
            notional_gallons=3000000,
            strike_usd_per_gal=2.4000,
            maturity_month="2027-02",
        )
        ctx["collar"] = fx.do_propose_collar(
            api,
            program_id,
            ctx["dealer_b"]["id"],
            notional_gallons=2000000,
            cap_strike_usd_per_gal=2.7000,
            floor_strike_usd_per_gal=2.1000,
            maturity_month="2027-03",
        )
        fx.do_submit_program(api, program_id)
        ctx["program"] = fx.do_activate_program(api, program_id)
        return ctx

    def test_the_collar_enters_the_delta_basis_at_sixty_five_percent_of_notional(
        self, api
    ):
        """PRD §3.4: "On the delta-adjusted basis, the programme's
        `delta_adjusted_gallons` is the sum of the children's own
        `delta_adjusted_gallons` over the same executed set, and
        `coverage_pct_delta` is derived from it the same way — so a collar
        contributes only 65 percent of its notional and a call option only 50
        percent, and an identical book therefore reads materially lower on the
        delta basis than on the notional basis."

        Five million gallons of notional over an 11,000,000-gallon basis is
        45.45 percent, while 3,000,000 plus 1,300,000 delta-adjusted gallons is
        39.09 percent — one book, two figures, both stored.

        Design: Difficulty/dual_variant_calc/coverage_notional_basis_vs_delta_adjusted_basis
        """
        ctx = self._book_of_one_swap_and_one_collar(api)

        swap = fx.do_execute_instrument(api, ctx["swap"]["id"])
        collar = fx.do_execute_instrument(api, ctx["collar"]["id"])

        assert_instrument_status(swap, trade_status="EXECUTED")
        assert_instrument_ledgers(
            swap, delta_factor=1.00, delta_adjusted_gallons=3000000.00
        )
        assert_instrument_status(collar, trade_status="EXECUTED")
        assert_instrument_ledgers(
            collar, delta_factor=0.65, delta_adjusted_gallons=1300000.00
        )

        program = fx.read_program(api, ctx["program"]["id"])
        assert_program_coverage(
            program,
            consumption_basis_gallons=11000000,
            hedged_gallons=5000000,
            delta_adjusted_gallons=4300000.00,
            coverage_pct_notional=45.45,
            coverage_pct_delta=39.09,
            open_instrument_count=2,
        )
        assert program["coverage_pct_notional"] != program["coverage_pct_delta"]

    def test_the_two_bases_agree_until_the_collar_is_executed(self, api):
        """PRD §3.4: "On the notional basis, `hedged_gallons` is the sum of
        `notional_gallons` over the programme's children whose `trade_status` is
        `EXECUTED`, and `coverage_pct_notional` is that sum divided by
        `consumption_basis_gallons`, multiplied by 100 and rounded to two decimal
        places; when the basis is zero the percentage is 0.00."

        The divergence is caused by the collar and by nothing else: with only
        the swap executed, a delta factor of 1.00 makes the two figures identical
        at 27.27 percent, and the second execution is what pushes them apart.

        Design: Difficulty/dual_variant_calc/coverage_notional_basis_vs_delta_adjusted_basis
        """
        ctx = self._book_of_one_swap_and_one_collar(api)

        fx.do_execute_instrument(api, ctx["swap"]["id"])
        after_swap = fx.read_program(api, ctx["program"]["id"])
        assert_program_coverage(
            after_swap,
            hedged_gallons=3000000,
            delta_adjusted_gallons=3000000.00,
            coverage_pct_notional=27.27,
            coverage_pct_delta=27.27,
        )
        assert after_swap["coverage_pct_notional"] == after_swap["coverage_pct_delta"]

        fx.do_execute_instrument(api, ctx["collar"]["id"])
        after_collar = fx.read_program(api, ctx["program"]["id"])
        assert_pct(after_collar["coverage_pct_notional"], 45.45, "coverage_pct_notional")
        assert_pct(after_collar["coverage_pct_delta"], 39.09, "coverage_pct_delta")
        assert (
            after_collar["coverage_pct_notional"] > after_collar["coverage_pct_delta"]
        )


class TestTankeringOnTwoBases:
    def test_the_planned_basis_prices_the_request_over_the_planned_block(self, api):
        """PRD §3.8: "On the **planned basis**, in force at creation and at every
        revision, the uplift is the directive's `requested_uplift_gallons`, the
        block time is the leg's `planned_block_minutes`, and both prices are read
        live from the active supply contracts at the moment of the call."

        PRD §3.8: "Net savings are the gross savings less the penalty cost,
        rounded to two decimal places — the three dollar figures are each rounded
        independently, and gross and penalty are never summed before rounding."

        Three thousand gallons over a 210-minute block carries a 368.9-gallon
        penalty: 1,890.00 of gross saving against 911.18 of penalty cost leaves
        978.82, and approval freezes the two prices that produced it.

        Design: Difficulty/dual_variant_calc/tankering_planned_basis_vs_reconciled_basis
        """
        ctx = fx.setup_approved_directive(
            api, 3000, policy_overrides=dict(policy_code="FY27-DV2")
        )
        directive = ctx["directive"]

        assert directive["status"] == "APPROVED"
        assert_planned_economics(
            directive,
            planned_burn_penalty_gallons=368.9,
            planned_gross_savings_usd=1890.00,
            planned_penalty_cost_usd=911.18,
            planned_net_savings_usd=978.82,
        )
        assert_pinned_prices(
            directive,
            pinned_origin_price_usd_per_gal=2.4700,
            pinned_destination_price_usd_per_gal=3.1000,
            pinned_origin_contract_ref="ORD-2027-A",
        )

    def test_the_reconciled_basis_reprices_the_flown_gallons_at_the_pinned_prices(
        self, api
    ):
        """PRD §3.8: "On the **reconciled basis**, the uplift is the leg's
        `actual_uplift_gallons`, the block time is the leg's
        `actual_block_minutes`, and the two prices are the pinned values frozen
        at approval; the payload hinge is re-evaluated from the actual uplift, so
        a smaller actual uplift can drop the penalty multiplier back to exactly
        1.0000."

        PRD §3.8: "The results are written to `reconciled_burn_penalty_gallons`
        and `reconciled_net_savings_usd`, and `savings_variance_usd` is the
        reconciled net savings less the planned net savings, rounded to two
        decimal places."

        Two thousand six hundred gallons flown over 250 minutes yields a
        341.9-gallon penalty and 793.51 net, which is 185.31 short of the plan.

        Design: Difficulty/dual_variant_calc/tankering_planned_basis_vs_reconciled_basis
        """
        ctx = fx.setup_loaded_directive(
            api, 3000, policy_overrides=dict(policy_code="FY27-DV2")
        )

        reconciled = fx.do_reconcile_directive(api, ctx["directive"]["id"], 2600, 250)

        assert reconciled["status"] == "RECONCILED"
        assert_reconciled_economics(
            reconciled,
            reconciled_burn_penalty_gallons=341.9,
            reconciled_net_savings_usd=793.51,
            savings_variance_usd=-185.31,
        )
        assert_pinned_prices(
            reconciled,
            pinned_origin_price_usd_per_gal=2.4700,
            pinned_destination_price_usd_per_gal=3.1000,
            pinned_origin_contract_ref="ORD-2027-A",
        )

    def test_the_planned_figures_survive_reconciliation_unchanged(self, api):
        """PRD §3.8: "Reconciliation later prices against those pinned values and
        never against live contracts, so a post-approval contract renegotiation
        cannot move the reconciled outcome."

        The two bases are stored side by side rather than one overwriting the
        other: the planned 368.9 and 978.82 are still on the row after the
        reconciled 341.9 and 793.51 have been written beside them, which is what
        makes the variance auditable.

        Design: Difficulty/dual_variant_calc/tankering_planned_basis_vs_reconciled_basis
        """
        ctx = fx.setup_loaded_directive(
            api, 3000, policy_overrides=dict(policy_code="FY27-DV2")
        )
        fx.do_reconcile_directive(api, ctx["directive"]["id"], 2600, 250)

        directive = fx.read_directive(api, ctx["directive"]["id"])
        assert_planned_economics(
            directive,
            planned_burn_penalty_gallons=368.9,
            planned_gross_savings_usd=1890.00,
            planned_penalty_cost_usd=911.18,
            planned_net_savings_usd=978.82,
        )
        assert_reconciled_economics(
            directive,
            reconciled_burn_penalty_gallons=341.9,
            reconciled_net_savings_usd=793.51,
            savings_variance_usd=-185.31,
        )
        assert_money(
            directive["savings_variance_usd"],
            round(directive["reconciled_net_savings_usd"], 2)
            - round(directive["planned_net_savings_usd"], 2),
            "savings_variance_usd",
        )

    def test_the_payload_hinge_is_re_evaluated_even_though_the_block_time_grew(
        self, api
    ):
        """PRD §3.8: "Second, the penalty multiplier is one plus the excess of
        that payload ratio over the hinge point of 0.85 — where that excess is
        positive, and zero when the ratio is at or below the hinge — multiplied
        by a slope of 2.0, the whole rounded to four decimal places; a lightly
        loaded aircraft therefore carries a multiplier of exactly 1.0000."

        PRD §3.8: "Third, the raw carriage burn is the uplift multiplied by a
        fleet factor of 0.030 for a `NARROWBODY`, 0.024 for a `WIDEBODY` or 0.038
        for a `REGIONAL`, multiplied by the block time expressed in hours as the
        block minutes divided by 60 — that quotient is never rounded."

        The block time grew from 210 to 250 minutes, yet the penalty fell,
        because 2,600 gallons moves the payload ratio from 0.9356 to 0.8760 and
        the multiplier from 1.1712 to 1.0520: a raw 325.0-gallon carriage burn
        scaled by 1.0520 is 341.9, not the 380.6 the planned multiplier would
        have produced.

        Design: Difficulty/dual_variant_calc/tankering_planned_basis_vs_reconciled_basis
        """
        ctx = fx.setup_loaded_directive(
            api, 3000, policy_overrides=dict(policy_code="FY27-DV2")
        )
        reconciled = fx.do_reconcile_directive(api, ctx["directive"]["id"], 2600, 250)

        assert_gallon_tenths(
            reconciled["reconciled_burn_penalty_gallons"],
            341.9,
            "reconciled_burn_penalty_gallons",
        )
        assert (
            reconciled["reconciled_burn_penalty_gallons"]
            < reconciled["planned_burn_penalty_gallons"]
        )

        leg = fx.read_flight_leg(api, ctx["leg"]["id"])
        assert_whole_gallons(leg["actual_uplift_gallons"], 2600, "actual_uplift_gallons")
        assert leg["actual_block_minutes"] == 250
        assert leg["planned_block_minutes"] == 210


class TestEffectivenessOnTwoBases:
    @staticmethod
    def _executed_swap_with_no_tests_yet(api):
        ctx = fx.setup_active_program_with_executed_swap(
            api,
            policy_overrides=dict(policy_code="FY27-DV3", min_coverage_pct=5.00),
            counterparty_overrides=DEALER_A,
            program_overrides=dict(program_code="HP-DV3", target_coverage_pct=10.00),
            swap_overrides=dict(
                notional_gallons=1000000,
                strike_usd_per_gal=2.4000,
                maturity_month="2027-03",
            ),
        )
        assert_instrument_status(
            ctx["instrument"],
            trade_status="EXECUTED",
            accounting_status="UNDESIGNATED",
        )
        return ctx

    def test_the_first_test_reads_the_same_ratio_on_both_bases(self, api):
        """PRD §3.6: "The period ratio is the absolute value of
        `hedge_change_usd` divided by `hedged_item_change_usd`, rounded to four
        decimal places, and is stored in `period_ratio` purely for the monthly
        effectiveness memo — a single ugly month reads as a failure here without
        consequence."

        With no prior test to accumulate, the cumulative totals are this test's
        own amounts, so 110,000 against 100,000 reads 1.1000 twice over and sits
        inside the corridor.

        Design: Difficulty/dual_variant_calc/effectiveness_period_basis_vs_cumulative_basis
        """
        ctx = self._executed_swap_with_no_tests_yet(api)

        first = fx.do_file_effectiveness_test(
            api, ctx["instrument"]["id"], "2027-01", -110000.00, 100000.00
        )
        assert_effectiveness_outcome(
            first, period_ratio=1.1000, cumulative_ratio=1.1000, result="PASS"
        )

    def test_a_period_ratio_far_outside_the_corridor_still_passes_on_the_cumulative(
        self, api
    ):
        """PRD §3.6: "The `result` field is `PASS` when the rounded
        `cumulative_ratio` falls between 0.8000 and 1.2500 with both bounds
        inclusive, and `FAIL` otherwise. Because the decision reads the
        cumulative figure, a `period_ratio` of 0.5000 can still produce a `PASS`
        when the cumulative ratio lands at 0.8000."

        The February month on its own is a 0.5000 disaster, but the running
        totals of -160,000.00 over 200,000.00 land exactly on the inclusive lower
        bound, and it is the cumulative figure that decides.

        Design: Difficulty/dual_variant_calc/effectiveness_period_basis_vs_cumulative_basis
        """
        ctx = self._executed_swap_with_no_tests_yet(api)
        fx.do_file_effectiveness_test(
            api, ctx["instrument"]["id"], "2027-01", -110000.00, 100000.00
        )

        second = fx.do_file_effectiveness_test(
            api, ctx["instrument"]["id"], "2027-02", -50000.00, 100000.00
        )
        assert_effectiveness_outcome(
            second, period_ratio=0.5000, cumulative_ratio=0.8000, result="PASS"
        )

    def test_the_running_totals_carry_both_tests_and_no_cascade_fires(self, api):
        """PRD §3.6: "The authoritative measure is cumulative: the trade's
        running `cumulative_hedge_change_usd` is advanced by this test's
        `hedge_change_usd` and its running `cumulative_item_change_usd` by this
        test's `hedged_item_change_usd` — these two totals accumulate every prior
        test of that instrument in `created_at` ascending order and no test is
        ever excluded once written".

        PRD §3.6: "If the posture stays `COMPLIANT`, the third and fourth hops do
        not run at all, and a `FAIL` on a trade that was not `DESIGNATED`
        triggers no cascade whatsoever."

        The instrument was never designated, so the accounting dimension is
        untouched by either filing and the trade dimension stays `EXECUTED`.

        Design: Difficulty/dual_variant_calc/effectiveness_period_basis_vs_cumulative_basis
        """
        ctx = self._executed_swap_with_no_tests_yet(api)
        fx.do_file_effectiveness_test(
            api, ctx["instrument"]["id"], "2027-01", -110000.00, 100000.00
        )
        fx.do_file_effectiveness_test(
            api, ctx["instrument"]["id"], "2027-02", -50000.00, 100000.00
        )

        instrument = fx.read_instrument(api, ctx["instrument"]["id"])
        assert_instrument_ledgers(
            instrument,
            cumulative_hedge_change_usd=-160000.00,
            cumulative_item_change_usd=200000.00,
        )
        assert_instrument_status(
            instrument, trade_status="EXECUTED", accounting_status="UNDESIGNATED"
        )
