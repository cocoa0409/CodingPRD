"""One gallon, one cent and one gallon of stock, either side of a threshold.

Each pair here is separated by the smallest step the field allows: a coverage
ceiling that is inclusive on the exact figure but rejects one extra gallon, an
effectiveness bound that is decided after rounding rather than before, and a
days-of-cover tier that is compared on the rounded quotient.
"""

from test_helpers import (
    ERR_COVERAGE_LIMIT_EXCEEDED,
    TREASURY,
    assert_counterparty_credit,
    assert_effectiveness_outcome,
    assert_instrument_ledgers,
    assert_instrument_status,
    assert_program_coverage,
    assert_station_supply,
    fixtures as fx,
    validate_error,
)

#: The dealer of the ceiling scenario, wide enough that credit never binds.
CEILING_DEALER = dict(
    counterparty_code="DLRA",
    legal_name="Dealer A Bank NA",
    credit_rating="AA",
    credit_limit_usd=2000000.00,
)

#: Exactly 60.00 percent of an 11,000,000-gallon basis.
EXACT_CEILING_GALLONS = 6600000


class TestCoverageCeilingExactEqualityAndOneGallon:
    @staticmethod
    def _active_program_with_an_exact_swap_and_a_one_gallon_swap(api):
        ctx = fx.setup_sized_program(
            api,
            policy_overrides=dict(
                policy_code="FY27-BP1", max_single_counterparty_pct=100.00
            ),
            counterparty_overrides=CEILING_DEALER,
            program_overrides=dict(program_code="HP-BP1", target_coverage_pct=60.00),
        )
        program_id = ctx["program"]["id"]
        counterparty_id = ctx["counterparty"]["id"]
        ctx["exact"] = fx.do_propose_swap(
            api,
            program_id,
            counterparty_id,
            notional_gallons=EXACT_CEILING_GALLONS,
            strike_usd_per_gal=2.4000,
            maturity_month="2027-03",
        )
        ctx["epsilon"] = fx.do_propose_swap(
            api,
            program_id,
            counterparty_id,
            notional_gallons=1,
            strike_usd_per_gal=2.4000,
            maturity_month="2027-03",
        )
        fx.do_submit_program(api, program_id)
        ctx["program"] = fx.do_activate_program(api, program_id)
        return ctx

    def test_a_book_landing_exactly_on_the_ceiling_is_admitted(self, api):
        """PRD §3.4: "The post-trade delta-adjusted coverage must not exceed the
        governing policy's `max_coverage_pct`, and this comparison is deliberately
        made on the *unrounded* quotient — the delta-adjusted gallons the programme
        would hold after this trade, divided by `consumption_basis_gallons` and
        multiplied by 100, with no rounding applied before the comparison."

        Six million six hundred thousand delta gallons over an 11,000,000-gallon
        basis is exactly 60.00 percent, and "must not exceed" admits equality: the
        trade executes and the stored percentage reads 60.00.

        Design: Difficulty/boundary_precision_check/coverage_ceiling_exact_equality_versus_one_gallon_epsilon
        """
        ctx = self._active_program_with_an_exact_swap_and_a_one_gallon_swap(api)

        executed = fx.do_execute_instrument(api, ctx["exact"]["id"])
        assert_instrument_status(executed, trade_status="EXECUTED")
        assert_instrument_ledgers(executed, margin_requirement_usd=396000.00)

        assert_program_coverage(
            fx.read_program(api, ctx["program"]["id"]),
            consumption_basis_gallons=11000000,
            hedged_gallons=6600000,
            delta_adjusted_gallons=6600000.00,
            coverage_pct_delta=60.00,
        )

    def test_one_more_gallon_is_refused_although_the_stored_figure_would_not_move(
        self, api
    ):
        """PRD §3.4: "A book that would land at 60.00000909 percent against a 60.00
        percent ceiling is therefore rejected with `ERR_COVERAGE_LIMIT_EXCEEDED`
        even though `coverage_pct_delta` would have stored 60.00."

        The second trade is a single gallon. Rounded to two decimal places the
        programme would still read 60.00, and it is refused anyway, because the
        comparison never sees the rounded field.

        Design: Difficulty/boundary_precision_check/coverage_ceiling_exact_equality_versus_one_gallon_epsilon
        """
        ctx = self._active_program_with_an_exact_swap_and_a_one_gallon_swap(api)
        fx.do_execute_instrument(api, ctx["exact"]["id"])

        validate_error(
            api.execute_hedge_instrument(ctx["epsilon"]["id"], headers=TREASURY),
            ERR_COVERAGE_LIMIT_EXCEEDED,
            422,
        )

    def test_the_refused_gallon_leaves_the_book_exactly_on_the_ceiling(self, api):
        """PRD §3.4: "Execution then cascades. It writes the new
        `margin_requirement_usd`, adds that amount to the counterparty's
        `utilized_credit_usd` and recomputes the counterparty's `utilization_pct`
        and `credit_posture`; it adds the trade's `notional_gallons` to the
        programme's `hedged_gallons` and the trade's `delta_adjusted_gallons` to the
        programme's `delta_adjusted_gallons` and recomputes all three coverage
        percentages; and it increments the instrument's, the counterparty's and the
        programme's `version` by one each."

        The refusal happens before any of that: the one-gallon trade is still
        `PROPOSED` with no requirement, the programme still holds exactly 6,600,000
        gallons at 60.00 percent, and the dealer still draws the 396,000.00 the
        first trade cost — 19.80 percent of a 2,000,000.00 limit.

        Design: Difficulty/boundary_precision_check/coverage_ceiling_exact_equality_versus_one_gallon_epsilon
        """
        ctx = self._active_program_with_an_exact_swap_and_a_one_gallon_swap(api)
        fx.do_execute_instrument(api, ctx["exact"]["id"])
        validate_error(
            api.execute_hedge_instrument(ctx["epsilon"]["id"], headers=TREASURY),
            ERR_COVERAGE_LIMIT_EXCEEDED,
            422,
        )

        epsilon = fx.read_instrument(api, ctx["epsilon"]["id"])
        assert_instrument_status(epsilon, trade_status="PROPOSED")
        assert_instrument_ledgers(epsilon, margin_requirement_usd=0)

        assert_program_coverage(
            fx.read_program(api, ctx["program"]["id"]),
            hedged_gallons=6600000,
            coverage_pct_delta=60.00,
        )
        assert_counterparty_credit(
            fx.read_counterparty(api, ctx["counterparty"]["id"]),
            utilized_credit_usd=396000.00,
            utilization_pct=19.80,
        )


class TestEffectivenessLowerBoundAfterRounding:
    @staticmethod
    def _two_executed_swaps_with_no_tests_yet(api):
        """Two identical million-gallon swaps, so each can carry a single test
        without accumulating the other's amounts."""
        ctx = fx.setup_sized_program(
            api,
            policy_overrides=dict(
                policy_code="FY27-BP2", max_earnings_volatility_usd=500000.00
            ),
            counterparty_overrides=dict(
                counterparty_code="DLRA",
                legal_name="Dealer A Bank NA",
                credit_rating="A",
                credit_limit_usd=1000000.00,
            ),
            program_overrides=dict(program_code="HP-BP2", target_coverage_pct=20.00),
        )
        program_id = ctx["program"]["id"]
        counterparty_id = ctx["counterparty"]["id"]
        ctx["passing"] = fx.do_propose_swap(
            api,
            program_id,
            counterparty_id,
            notional_gallons=1000000,
            strike_usd_per_gal=2.4000,
            maturity_month="2027-03",
        )
        ctx["failing"] = fx.do_propose_swap(
            api,
            program_id,
            counterparty_id,
            notional_gallons=1000000,
            strike_usd_per_gal=2.4100,
            maturity_month="2027-03",
        )
        fx.do_submit_program(api, program_id)
        fx.do_activate_program(api, program_id)
        ctx["passing"] = fx.do_execute_instrument(api, ctx["passing"]["id"])
        ctx["failing"] = fx.do_execute_instrument(api, ctx["failing"]["id"])
        return ctx

    def test_a_ratio_below_the_bound_that_rounds_onto_it_passes(self, api):
        """PRD §3.6: "`cumulative_ratio` is the absolute value of the new cumulative
        hedge change divided by the new cumulative item change, rounded to four
        decimal places. The `result` field is `PASS` when the rounded
        `cumulative_ratio` falls between 0.8000 and 1.2500 with both bounds
        inclusive, and `FAIL` otherwise."

        Seventy-nine thousand nine hundred and ninety-five dollars over a hundred
        thousand is 0.79995, which is strictly below the bound before rounding and
        exactly on it after: the decision reads the rounded figure, so this is a
        `PASS`.

        Design: Difficulty/boundary_precision_check/effectiveness_lower_bound_inclusive_after_rounding
        """
        ctx = self._two_executed_swaps_with_no_tests_yet(api)

        passing = fx.do_file_effectiveness_test(
            api, ctx["passing"]["id"], "2027-02", -79995.00, 100000.00
        )
        assert_effectiveness_outcome(
            passing, period_ratio=0.8000, cumulative_ratio=0.8000, result="PASS"
        )

    def test_one_dollar_less_of_offset_rounds_below_the_bound_and_fails(self, api):
        """PRD §3.6: "The period ratio is the absolute value of `hedge_change_usd`
        divided by `hedged_item_change_usd`, rounded to four decimal places, and is
        stored in `period_ratio` purely for the monthly effectiveness memo — a
        single ugly month reads as a failure here without consequence."

        A dollar less of hedge change makes the quotient 0.79994, which rounds to
        0.7999 and lands outside the corridor: two filings a dollar apart, and the
        `result` column disagrees.

        Design: Difficulty/boundary_precision_check/effectiveness_lower_bound_inclusive_after_rounding
        """
        ctx = self._two_executed_swaps_with_no_tests_yet(api)

        failing = fx.do_file_effectiveness_test(
            api, ctx["failing"]["id"], "2027-02", -79994.00, 100000.00
        )
        assert_effectiveness_outcome(
            failing, period_ratio=0.7999, cumulative_ratio=0.7999, result="FAIL"
        )

    def test_both_filings_record_their_totals_and_the_failure_cascades_nowhere(
        self, api
    ):
        """PRD §3.6: "The authoritative measure is cumulative: the trade's running
        `cumulative_hedge_change_usd` is advanced by this test's `hedge_change_usd`
        and its running `cumulative_item_change_usd` by this test's
        `hedged_item_change_usd`".

        PRD §3.6: "If the posture stays `COMPLIANT`, the third and fourth hops do
        not run at all, and a `FAIL` on a trade that was not `DESIGNATED` triggers
        no cascade whatsoever."

        Neither trade was ever designated, so the `FAIL` costs nothing: no
        exception is counted on the policy, both trades stay `UNDESIGNATED` and the
        programme still reads 18.18 percent of delta coverage.

        Design: Difficulty/boundary_precision_check/effectiveness_lower_bound_inclusive_after_rounding
        """
        ctx = self._two_executed_swaps_with_no_tests_yet(api)
        fx.do_file_effectiveness_test(
            api, ctx["passing"]["id"], "2027-02", -79995.00, 100000.00
        )
        fx.do_file_effectiveness_test(
            api, ctx["failing"]["id"], "2027-02", -79994.00, 100000.00
        )

        passing = fx.read_instrument(api, ctx["passing"]["id"])
        assert_instrument_ledgers(
            passing,
            cumulative_hedge_change_usd=-79995.00,
            cumulative_item_change_usd=100000.00,
        )
        failing = fx.read_instrument(api, ctx["failing"]["id"])
        assert_instrument_ledgers(
            failing,
            cumulative_hedge_change_usd=-79994.00,
            cumulative_item_change_usd=100000.00,
        )
        assert_instrument_status(passing, accounting_status="UNDESIGNATED")
        assert_instrument_status(failing, accounting_status="UNDESIGNATED")

        assert fx.read_policy(api, ctx["policy"]["id"])["open_exception_count"] == 0
        assert_program_coverage(
            fx.read_program(api, ctx["program"]["id"]), coverage_pct_delta=18.18
        )


class TestStationDaysCoverBoundaries:
    @staticmethod
    def _empty_station_under_a_three_day_minimum(api):
        policy = fx.do_create_policy(api, policy_code="FY27-BP3")
        station = fx.do_create_station(api)
        assert_station_supply(station, inventory_gallons=0.00, days_cover=0.00)
        return {"policy": policy, "station": station}

    def test_two_point_nine_nine_days_of_cover_is_short(self, api):
        """PRD §3.2: "The rounded `days_cover` is then compared against the
        `min_days_cover` of the single `ACTIVE` hedging policy to set
        `supply_posture`: below that minimum the station is `SHORT`; from the minimum
        up to but not including twice the minimum it is `WATCH`; and at twice the
        minimum or above it is `NORMAL`."

        Two hundred and ninety-nine thousand gallons over a hundred thousand daily
        liftings is 2.99 days even after rounding, which is genuinely below the
        three-day minimum.

        Design: Difficulty/boundary_precision_check/station_days_cover_min_boundary_and_rounding_lift
        """
        ctx = self._empty_station_under_a_three_day_minimum(api)

        station = fx.do_adjust_inventory(api, ctx["station"]["id"], 299000)
        assert_station_supply(
            station,
            inventory_gallons=299000.00,
            effective_inventory_gallons=299000.00,
            days_cover=2.99,
            supply_posture="SHORT",
        )

    def test_one_gallon_short_of_the_floor_is_rounded_up_into_watch(self, api):
        """PRD §3.2: "Third, `days_cover` is `effective_inventory_gallons` divided
        by `avg_daily_liftings_gallons`, rounded to two decimal places."

        At 299,999 gallons the true cover is 2.99999 days, which is below the
        minimum, but the comparison reads the rounded 3.00: one gallon moves the
        station out of `SHORT` because the rounding happens first.

        Design: Difficulty/boundary_precision_check/station_days_cover_min_boundary_and_rounding_lift
        """
        ctx = self._empty_station_under_a_three_day_minimum(api)
        fx.do_adjust_inventory(api, ctx["station"]["id"], 299000)

        station = fx.do_adjust_inventory(api, ctx["station"]["id"], 999)
        assert_station_supply(
            station,
            inventory_gallons=299999.00,
            days_cover=3.00,
            supply_posture="WATCH",
        )

    def test_exact_equality_with_the_minimum_is_watch_and_never_short(self, api):
        """PRD §3.2: "A station whose `days_cover` is exactly equal to
        `min_days_cover` is therefore `WATCH`, never `SHORT`."

        A round 300,000 gallons is exactly three days of cover, and the tier below
        is exclusive at its top end, so the posture is the same `WATCH` the rounded
        299,999 produced.

        Design: Difficulty/boundary_precision_check/station_days_cover_min_boundary_and_rounding_lift
        """
        ctx = self._empty_station_under_a_three_day_minimum(api)
        fx.do_adjust_inventory(api, ctx["station"]["id"], 299000)
        fx.do_adjust_inventory(api, ctx["station"]["id"], 999)

        station = fx.do_adjust_inventory(api, ctx["station"]["id"], 1)
        assert_station_supply(
            station,
            inventory_gallons=300000.00,
            days_cover=3.00,
            supply_posture="WATCH",
        )

    def test_the_upper_tier_boundary_is_reached_by_the_same_rounding_lift(self, api):
        """PRD §3.2: "Each adjustment recomputes the station's derived supply fields
        and increments the station's `version` by one."

        PRD §3.2: "at twice the minimum or above it is `NORMAL`."

        Five hundred and ninety-nine thousand gallons is 5.99 days and still
        `WATCH`; 999 gallons more is 5.99999 days, which rounds to the 6.00 that the
        upper tier includes, so the station reads `NORMAL` one gallon before it
        truly holds six days of stock.

        Design: Difficulty/boundary_precision_check/station_days_cover_min_boundary_and_rounding_lift
        """
        ctx = self._empty_station_under_a_three_day_minimum(api)
        for delta in (299000, 999, 1):
            fx.do_adjust_inventory(api, ctx["station"]["id"], delta)

        watch = fx.do_adjust_inventory(api, ctx["station"]["id"], 299000)
        assert_station_supply(
            watch,
            inventory_gallons=599000.00,
            days_cover=5.99,
            supply_posture="WATCH",
        )

        normal = fx.do_adjust_inventory(api, ctx["station"]["id"], 999)
        assert_station_supply(
            normal,
            inventory_gallons=599999.00,
            days_cover=6.00,
            supply_posture="NORMAL",
        )
