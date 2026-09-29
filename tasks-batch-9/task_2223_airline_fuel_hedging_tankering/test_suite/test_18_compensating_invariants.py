"""Undo operations, and the ledgers they are and are not allowed to touch.

Returning collateral restores the collateral ledgers to the cent and leaves the
credit ledger exactly where it was. Terminating a trade restores four ledgers at
once while the trade row keeps its own figures for audit. Reconciling a directive
posts a compensating true-up rather than a second debit, so the station's net
movement equals the gallons actually lifted.
"""

from test_helpers import (
    ERR_PROGRAM_HAS_OPEN_INSTRUMENTS,
    TREASURY,
    assert_counterparty_credit,
    assert_instrument_ledgers,
    assert_instrument_status,
    assert_money,
    assert_program_coverage,
    assert_station_supply,
    assert_whole_gallons,
    fixtures as fx,
    validate_error,
)

DEALER_A = dict(
    counterparty_code="DLRA",
    legal_name="Dealer A Bank NA",
    credit_rating="A",
    credit_limit_usd=1000000.00,
)

#: The 3,000,000-gallon swap both hedging scenarios in this file carry: 0.06 a
#: gallon of base margin is 180,000.00, and 27.27 percent of an 11,000,000-gallon
#: basis.
BIG_SWAP = dict(
    notional_gallons=3000000,
    strike_usd_per_gal=2.4000,
    maturity_month="2027-03",
)
BIG_SWAP_MARGIN_USD = 180000.00

#: More cash than the requirement asks for.
OVER_POSTED_USD = 250000.00

#: The tankering scenario's clock, opening stock and lifted gallons.
CI3_CLOCK = "2027-02-10T00:00:00Z"
OPENING_STOCK_GALLONS = 500000
REQUESTED_UPLIFT_GALLONS = 3000
ACTUAL_UPLIFT_GALLONS = 2600


def _posting_by_id(api, instrument_id, posting_id):
    """Collateral rows are readable only through their parents' lists."""
    rows = fx.list_instrument_postings(api, instrument_id)
    matches = [row for row in rows if row["id"] == posting_id]
    assert matches, f"posting {posting_id} not listed under instrument {instrument_id}"
    return matches[0]


class TestCollateralReturnConservesThePostedLedgerOnly:
    @staticmethod
    def _executed_trade_with_an_open_requirement(api):
        ctx = fx.setup_active_program_with_executed_swap(
            api,
            policy_overrides=dict(policy_code="FY27-CI1"),
            counterparty_overrides=DEALER_A,
            program_overrides=dict(program_code="HP-CI1", target_coverage_pct=28.00),
            swap_overrides=BIG_SWAP,
        )
        ctx["posting"] = fx.do_create_posting(
            api, ctx["counterparty"]["id"], ctx["instrument"]["id"]
        )
        return ctx

    def test_over_posting_moves_both_collateral_ledgers_by_the_offered_amount(
        self, api
    ):
        """PRD §3.5: "Posting writes `posted_amount_usd` from the offered amount,
        stamps `posted_at` from the logical clock, adds the posted amount to both the
        counterparty's `posted_collateral_usd` and the trade's
        `collateral_posted_usd`, decrements the counterparty's
        `open_margin_call_count` by one, and increments the posting's, the
        counterparty's and the trade's `version` by one each."

        The requirement froze at 180,000.00 and 250,000.00 is offered, which is
        allowed; both collateral ledgers take the offered figure, not the required
        one, and the call is no longer open.

        Design: Difficulty/compensating_invariant/collateral_return_conserves_posted_ledger_without_touching_credit
        """
        ctx = self._executed_trade_with_an_open_requirement(api)
        assert_money(
            ctx["posting"]["required_amount_usd"],
            BIG_SWAP_MARGIN_USD,
            "required_amount_usd",
        )
        assert_counterparty_credit(
            fx.read_counterparty(api, ctx["counterparty"]["id"]),
            posted_collateral_usd=0.00,
            open_margin_call_count=1,
        )
        assert_instrument_ledgers(
            fx.read_instrument(api, ctx["instrument"]["id"]), collateral_posted_usd=0.00
        )

        posted = fx.do_post_collateral(api, ctx["posting"]["id"], OVER_POSTED_USD)
        assert posted["status"] == "POSTED"
        assert_money(posted["posted_amount_usd"], OVER_POSTED_USD, "posted_amount_usd")

        assert_counterparty_credit(
            fx.read_counterparty(api, ctx["counterparty"]["id"]),
            posted_collateral_usd=OVER_POSTED_USD,
            open_margin_call_count=0,
        )
        assert_instrument_ledgers(
            fx.read_instrument(api, ctx["instrument"]["id"]),
            collateral_posted_usd=OVER_POSTED_USD,
        )

    def test_the_return_restores_the_collateral_ledgers_and_keeps_the_row(self, api):
        """PRD §3.5: "It is permitted in exactly two circumstances: the covered
        trade's `trade_status` is `SETTLED` or `TERMINATED`, or the trade's
        `margin_requirement_usd` has fallen strictly below its
        `collateral_posted_usd`, meaning collateral is now surplus to requirement."

        PRD §3.5: "Return stamps `returned_at` from the logical clock and subtracts
        `posted_amount_usd` from both the counterparty's `posted_collateral_usd` and
        the trade's `collateral_posted_usd`, incrementing all three rows' `version`
        by one; crucially, `posted_amount_usd` is retained on the row for audit and
        is *not* zeroed."

        The trade is still `EXECUTED` — what admits the return is 180,000.00 of
        margin sitting below 250,000.00 of collateral. Both ledgers land back on the
        exact 0.00 they held before the post, while the row keeps both of its own
        figures.

        Design: Difficulty/compensating_invariant/collateral_return_conserves_posted_ledger_without_touching_credit
        """
        ctx = self._executed_trade_with_an_open_requirement(api)
        fx.do_post_collateral(api, ctx["posting"]["id"], OVER_POSTED_USD)

        assert_instrument_status(
            fx.read_instrument(api, ctx["instrument"]["id"]), trade_status="EXECUTED"
        )
        returned = fx.do_return_collateral(
            api, ctx["posting"]["id"], "Excess margin recalled; requirement unchanged."
        )
        assert returned["status"] == "RETURNED"
        assert returned["returned_at"] is not None

        assert_counterparty_credit(
            fx.read_counterparty(api, ctx["counterparty"]["id"]),
            posted_collateral_usd=0.00,
        )
        assert_instrument_ledgers(
            fx.read_instrument(api, ctx["instrument"]["id"]), collateral_posted_usd=0.00
        )

        row = _posting_by_id(api, ctx["instrument"]["id"], ctx["posting"]["id"])
        assert_money(row["posted_amount_usd"], OVER_POSTED_USD, "posted_amount_usd")
        assert_money(
            row["required_amount_usd"], BIG_SWAP_MARGIN_USD, "required_amount_usd"
        )

    def test_the_credit_ledger_is_not_compensated_at_any_step(self, api):
        """PRD §3.1: "A counterparty's `utilized_credit_usd` is the sum of
        `margin_requirement_usd` over its trades whose trade dimension reads
        `EXECUTED`; its `posted_collateral_usd` is the sum of `posted_amount_usd`
        over its collateral rows in `POSTED` status; and `open_margin_call_count` is
        the number of its collateral rows still sitting in `REQUIRED`."

        Credit and collateral are two ledgers with two definitions. The post and the
        return move one of them by 250,000.00 in each direction and never touch the
        other: `utilized_credit_usd` reads 180,000.00 and `utilization_pct` 18.00 at
        all three observations, and the returned row does not re-open the call.

        Design: Difficulty/compensating_invariant/collateral_return_conserves_posted_ledger_without_touching_credit
        """
        ctx = self._executed_trade_with_an_open_requirement(api)
        counterparty_id = ctx["counterparty"]["id"]

        assert_counterparty_credit(
            fx.read_counterparty(api, counterparty_id),
            utilized_credit_usd=BIG_SWAP_MARGIN_USD,
            utilization_pct=18.00,
            credit_posture="NORMAL",
        )

        fx.do_post_collateral(api, ctx["posting"]["id"], OVER_POSTED_USD)
        assert_counterparty_credit(
            fx.read_counterparty(api, counterparty_id),
            utilized_credit_usd=BIG_SWAP_MARGIN_USD,
            utilization_pct=18.00,
            credit_posture="NORMAL",
        )

        fx.do_return_collateral(
            api, ctx["posting"]["id"], "Excess margin recalled; requirement unchanged."
        )
        assert_counterparty_credit(
            fx.read_counterparty(api, counterparty_id),
            utilized_credit_usd=BIG_SWAP_MARGIN_USD,
            posted_collateral_usd=0.00,
            utilization_pct=18.00,
            credit_posture="NORMAL",
            open_margin_call_count=0,
        )


class TestTerminationRestoresCoverageAndCredit:
    @staticmethod
    def _active_program_with_one_unexecuted_swap(api):
        return fx.setup_active_program_with_proposed_swap(
            api,
            policy_overrides=dict(policy_code="FY27-CI2"),
            counterparty_overrides=DEALER_A,
            program_overrides=dict(program_code="HP-CI2", target_coverage_pct=28.00),
            swap_overrides=BIG_SWAP,
        )

    def test_execution_moves_four_ledgers_off_their_opening_values(self, api):
        """PRD §3.4: "On the notional basis, `hedged_gallons` is the sum of
        `notional_gallons` over the programme's children whose `trade_status` is
        `EXECUTED`, and `coverage_pct_notional` is that sum divided by
        `consumption_basis_gallons`, multiplied by 100 and rounded to two decimal
        places; when the basis is zero the percentage is 0.00."

        PRD §3.1: "From those, `utilization_pct` is `utilized_credit_usd` divided by
        `credit_limit_usd`, multiplied by 100 and rounded to two decimal places."

        Before the execute all four ledgers are at their opening values with one
        instrument merely open; after it the book reads 3,000,000 gallons at 27.27
        percent on both bases and the dealer draws 18.00 percent of its limit.

        Design: Difficulty/compensating_invariant/terminate_restores_coverage_and_credit_to_pre_execution_values
        """
        ctx = self._active_program_with_one_unexecuted_swap(api)

        assert_program_coverage(
            fx.read_program(api, ctx["program"]["id"]),
            consumption_basis_gallons=11000000,
            hedged_gallons=0,
            delta_adjusted_gallons=0.00,
            coverage_pct_notional=0.00,
            coverage_pct_delta=0.00,
            open_instrument_count=1,
        )
        assert_counterparty_credit(
            fx.read_counterparty(api, ctx["counterparty"]["id"]),
            utilized_credit_usd=0.00,
            utilization_pct=0.00,
            credit_posture="NORMAL",
        )

        fx.do_execute_instrument(api, ctx["instrument"]["id"])

        assert_program_coverage(
            fx.read_program(api, ctx["program"]["id"]),
            hedged_gallons=3000000,
            delta_adjusted_gallons=3000000.00,
            coverage_pct_notional=27.27,
            coverage_pct_delta=27.27,
            planned_coverage_pct_delta=27.27,
        )
        assert_counterparty_credit(
            fx.read_counterparty(api, ctx["counterparty"]["id"]),
            utilized_credit_usd=BIG_SWAP_MARGIN_USD,
            utilization_pct=18.00,
        )

    def test_termination_returns_every_ledger_while_the_trade_keeps_its_figures(
        self, api
    ):
        """PRD §3.4: "The net effect is that `hedged_gallons`,
        `delta_adjusted_gallons`, `utilized_credit_usd` and `posted_collateral_usd`
        all return to their pre-execution values."

        PRD §3.4: "The first hop advances `trade_status` `EXECUTED → TERMINATED`,
        sets `margin_requirement_usd` to 0, moves `accounting_status` to
        `DEDESIGNATED` if and only if it was `DESIGNATED`, subtracts the trade's
        `notional_gallons` from the programme's `hedged_gallons` and its
        `delta_adjusted_gallons` from the programme's `delta_adjusted_gallons`,
        decrements `open_instrument_count` by one and recomputes all three coverage
        percentages."

        The compensation is exact on the programme and the dealer, and it is not a
        deletion: the terminated row still reports 3,000,000 notional gallons and
        3,000,000.00 delta-adjusted gallons for audit even though the programme has
        stopped counting them.

        Design: Difficulty/compensating_invariant/terminate_restores_coverage_and_credit_to_pre_execution_values
        """
        ctx = self._active_program_with_one_unexecuted_swap(api)
        fx.do_execute_instrument(api, ctx["instrument"]["id"])

        terminated = fx.do_terminate_instrument(
            api, ctx["instrument"]["id"], "Hedge unwound at the desk's request."
        )
        assert_instrument_status(terminated, trade_status="TERMINATED")
        assert_instrument_ledgers(
            terminated,
            margin_requirement_usd=0,
            delta_adjusted_gallons=3000000.00,
        )
        assert_whole_gallons(
            terminated["notional_gallons"], 3000000, "notional_gallons"
        )

        assert_program_coverage(
            fx.read_program(api, ctx["program"]["id"]),
            hedged_gallons=0,
            delta_adjusted_gallons=0.00,
            coverage_pct_notional=0.00,
            coverage_pct_delta=0.00,
            planned_coverage_pct_delta=0.00,
            open_instrument_count=0,
        )
        assert_counterparty_credit(
            fx.read_counterparty(api, ctx["counterparty"]["id"]),
            utilized_credit_usd=0.00,
            posted_collateral_usd=0.00,
            utilization_pct=0.00,
            credit_posture="NORMAL",
        )

    def test_closure_is_the_independent_witness_that_the_book_is_empty(self, api):
        """PRD §3.3: "**Closure** moves a programme `ACTIVE → CLOSED` and increments
        its `version`, and is permitted only when `open_instrument_count` has fallen
        to zero — every instrument on the book has either settled or been
        terminated."

        PRD §3.3: "Closing a programme that still has proposed or executed trades is
        rejected with `ERR_PROGRAM_HAS_OPEN_INSTRUMENTS`."

        Closure reads a counter no coverage assertion touches, so it corroborates the
        restoration from outside: refused while the trade is live, granted once the
        compensating termination has run.

        Design: Difficulty/compensating_invariant/terminate_restores_coverage_and_credit_to_pre_execution_values
        """
        ctx = self._active_program_with_one_unexecuted_swap(api)
        program_id = ctx["program"]["id"]
        fx.do_execute_instrument(api, ctx["instrument"]["id"])

        validate_error(
            api.close_hedge_program(program_id, headers=TREASURY),
            ERR_PROGRAM_HAS_OPEN_INSTRUMENTS,
            409,
        )
        assert fx.read_program(api, program_id)["status"] == "ACTIVE"

        fx.do_terminate_instrument(
            api, ctx["instrument"]["id"], "Hedge unwound at the desk's request."
        )

        closed = fx.do_close_program(api, program_id)
        assert closed["status"] == "CLOSED"


class TestStationGallonLedgerTruedUpAtReconciliation:
    @staticmethod
    def _approved_directive_over_a_fifty_day_station(api):
        """The baseline priced pair, except that the origin lifts only 10,000
        gallons a day, so a few hundred gallons are visible in `days_cover`."""
        fx.set_clock(api, CI3_CLOCK)
        ctx = {"policy": fx.do_create_policy(api, policy_code="FY27-CI3")}
        ctx["origin"] = fx.do_create_station(api, avg_daily_liftings_gallons=10000)
        ctx["destination"] = fx.do_create_station(
            api,
            iata_code="DFW",
            name="Dallas Fort Worth",
            into_plane_fee_usd_per_gal=0.0800,
        )
        fx.do_create_contract(api, ctx["origin"]["id"])
        fx.do_create_contract(
            api,
            ctx["destination"]["id"],
            contract_ref="DFW-2027-A",
            index_price_usd_per_gal=2.9000,
            differential_usd_per_gal=0.1200,
        )
        ctx["origin"] = fx.do_adjust_inventory(
            api, ctx["origin"]["id"], OPENING_STOCK_GALLONS, "Opening physical stock"
        )
        ctx["leg"] = fx.do_create_leg(
            api,
            ctx["origin"]["id"],
            ctx["destination"]["id"],
            flight_number="UA600",
            departure_date="2027-02-19",
        )
        ctx["directive"] = fx.do_propose_directive(
            api, ctx["leg"]["id"], REQUESTED_UPLIFT_GALLONS
        )
        ctx["directive"] = fx.do_approve_directive(api, ctx["directive"]["id"])
        return ctx

    def test_loading_debits_the_requested_gallons_not_the_flown_ones(self, api):
        """PRD §3.8: "Loading cascades in two hops: the first subtracts
        `requested_uplift_gallons` from the origin station's `inventory_gallons`, and
        the second fires because inventory moved, recomputing the origin station's
        `effective_inventory_gallons`, `days_cover` and `supply_posture`."

        Nobody knows yet what the aircraft actually took. The ledger moves on the
        requested 3,000 gallons, which is 500,000 down to 497,000 and fifty days of
        cover down to 49.70.

        Design: Difficulty/compensating_invariant/station_gallon_ledger_trued_up_at_reconciliation
        """
        ctx = self._approved_directive_over_a_fifty_day_station(api)
        assert_station_supply(
            fx.read_station(api, ctx["origin"]["id"]),
            inventory_gallons=500000.00,
            effective_inventory_gallons=500000.00,
            days_cover=50.00,
            supply_posture="NORMAL",
        )

        loaded = fx.do_load_directive(api, ctx["directive"]["id"])
        assert loaded["status"] == "EXECUTED"

        assert_station_supply(
            fx.read_station(api, ctx["origin"]["id"]),
            inventory_gallons=497000.00,
            days_cover=49.70,
            supply_posture="NORMAL",
        )

    def test_reconciliation_posts_a_true_up_rather_than_a_second_debit(self, api):
        """PRD §3.8: "Reconciliation also trues up the gallon ledger: the origin
        station's `inventory_gallons` is adjusted by the requested uplift less the
        actual uplift, so that the station's net debit across loading and
        reconciliation equals `actual_uplift_gallons` exactly; a smaller actual uplift
        credits gallons back, a larger one debits more."

        The flown figure is 2,600 gallons, so 400 come back rather than 2,600 going
        out again: the station reads 497,400 gallons, and 500,000 less that is
        exactly the 2,600 the leg now records.

        Design: Difficulty/compensating_invariant/station_gallon_ledger_trued_up_at_reconciliation
        """
        ctx = self._approved_directive_over_a_fifty_day_station(api)
        fx.do_load_directive(api, ctx["directive"]["id"])

        fx.do_reconcile_directive(
            api, ctx["directive"]["id"], ACTUAL_UPLIFT_GALLONS, 210
        )

        station = fx.read_station(api, ctx["origin"]["id"])
        assert_station_supply(
            station,
            inventory_gallons=497400.00,
            effective_inventory_gallons=497400.00,
            days_cover=49.74,
            supply_posture="NORMAL",
        )
        assert_whole_gallons(
            OPENING_STOCK_GALLONS - float(station["inventory_gallons"]),
            ACTUAL_UPLIFT_GALLONS,
            "net gallons debited",
        )

        leg = fx.read_flight_leg(api, ctx["leg"]["id"])
        assert_whole_gallons(
            leg["actual_uplift_gallons"], ACTUAL_UPLIFT_GALLONS, "actual_uplift_gallons"
        )
        assert leg["actual_block_minutes"] == 210

    def test_the_requested_figure_survives_on_the_directive(self, api):
        """PRD §3.8: "**Reconciling** the directive advances `EXECUTED → RECONCILED`
        against flown data."

        PRD §3.8: "Both values are written onto the leg, whose `version` is
        incremented by one."

        The true-up is a station-ledger movement and nothing else: the flown figures
        land on the leg, the directive still asks for the 3,000 gallons it always
        asked for, and the origin's posture never leaves `NORMAL`.

        Design: Difficulty/compensating_invariant/station_gallon_ledger_trued_up_at_reconciliation
        """
        ctx = self._approved_directive_over_a_fifty_day_station(api)
        fx.do_load_directive(api, ctx["directive"]["id"])

        reconciled = fx.do_reconcile_directive(
            api, ctx["directive"]["id"], ACTUAL_UPLIFT_GALLONS, 210
        )
        assert reconciled["status"] == "RECONCILED"
        assert_whole_gallons(
            reconciled["requested_uplift_gallons"],
            REQUESTED_UPLIFT_GALLONS,
            "requested_uplift_gallons",
        )
