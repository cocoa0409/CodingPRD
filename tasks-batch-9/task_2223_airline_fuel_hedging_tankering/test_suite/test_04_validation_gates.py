"""Hard limits, and the narrow channel that waives two of them.

Each gate here is checked twice over: once that the violation is reported with
the right code and nothing is written, and once — where the PRD provides a
waiver — that an approved exception flips the identical call to success.
"""

from test_helpers import (
    ADMIN,
    ANALYST,
    ERR_COVERAGE_FLOOR_NOT_MET,
    ERR_EXCEPTION_REQUIRED,
    ERR_INSTRUMENT_TYPE_NOT_PERMITTED,
    ERR_TANKERING_NOT_ECONOMIC,
    ERR_ZERO_UPLIFT,
    OPS,
    assert_instrument_ledgers,
    assert_instrument_status,
    assert_money,
    assert_pct,
    assert_pinned_prices,
    assert_planned_economics,
    assert_program_coverage,
    assert_station_supply,
    assert_undecided_exception,
    factories as f,
    fixtures as fx,
    make_analyst_headers,
    make_treasury_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

ANALYST_1 = "u_analyst_1"
TRM_1 = "u_trm_1"


class TestCoverageFloorOnActivation:
    @staticmethod
    def _submitted_programme_with_one_small_proposal(api):
        policy = fx.do_create_policy(
            api,
            policy_code="FY27-FLOOR",
            max_coverage_pct=60.00,
            min_coverage_pct=50.00,
            max_single_counterparty_pct=100.00,
            max_earnings_volatility_usd=500000.00,
            eligible_fleet_types=["NARROWBODY"],
        )
        counterparty = fx.do_create_counterparty(
            api,
            counterparty_code="DLRC",
            legal_name="Dealer C Bank NA",
            credit_rating="A",
        )
        fx.do_create_published_forecast(api)
        program = fx.do_create_program(
            api,
            policy["id"],
            program_code="HP-FLOOR",
            route_groups=["DOMESTIC_SHORT"],
            target_coverage_pct=55.00,
        )
        fx.do_size_program(api, program["id"])
        fx.do_propose_swap(
            api,
            program["id"],
            counterparty["id"],
            notional_gallons=400000,
            strike_usd_per_gal=2.5000,
            maturity_month="2027-03",
        )
        fx.do_submit_program(api, program["id"], ANALYST_1)
        return program

    def test_activation_is_refused_when_planned_coverage_sits_below_the_floor(self, api):
        """PRD §3.3: "The second is the coverage floor: the programme's
        `planned_coverage_pct_delta` must be greater than or equal to the
        governing policy's `min_coverage_pct`, otherwise
        `ERR_COVERAGE_FLOOR_NOT_MET`."

        PRD §2.5: "**Coverage floor** on programme activation, otherwise
        `ERR_COVERAGE_FLOOR_NOT_MET` (422)."

        Design: Corner/validations/activate_below_min_coverage_pct_returns_422_coverage_floor
        """
        program = self._submitted_programme_with_one_small_proposal(api)

        validate_error(
            api.activate_hedge_program(
                program["id"], headers=make_treasury_headers(TRM_1)
            ),
            ERR_COVERAGE_FLOOR_NOT_MET,
            422,
        )

    def test_the_floor_reads_the_planned_measure_and_the_refusal_changes_no_state(
        self, api
    ):
        """PRD §3.3: "Because the floor reads the *planned* measure, instruments
        that are still merely proposed count toward clearing it."

        PRD §3.4: "A third measure, `planned_coverage_pct_delta`, widens the
        input set to children whose `trade_status` is `PROPOSED` or `EXECUTED`,
        sums their `delta_adjusted_gallons`, and divides by the basis in the same
        way; this is the measure the activation floor reads."

        A 400,000-gallon swap against a 4,400,000-gallon basis plans 9.09 per
        cent while nothing is executed, and the refused activation is not a
        silent return to `SIZING`.

        Design: Corner/validations/activate_below_min_coverage_pct_returns_422_coverage_floor
        """
        program = self._submitted_programme_with_one_small_proposal(api)
        validate_error(
            api.activate_hedge_program(
                program["id"], headers=make_treasury_headers(TRM_1)
            ),
            ERR_COVERAGE_FLOOR_NOT_MET,
            422,
        )

        after = fx.read_program(api, program["id"])
        assert_program_coverage(
            after, planned_coverage_pct_delta=9.09, coverage_pct_delta=0.00
        )
        assert after["status"] == "PENDING_APPROVAL"
        assert after["submitted_by_user_id"] == ANALYST_1
        assert after["return_count"] == 0


class TestPermittedInstrumentTypes:
    @staticmethod
    def _swap_only_policy_with_a_sized_programme(api):
        policy = fx.do_create_policy(
            api,
            policy_code="FY27-SWAPONLY",
            min_coverage_pct=5.00,
            max_single_counterparty_pct=100.00,
            max_earnings_volatility_usd=500000.00,
            permitted_instrument_types=["SWAP"],
            eligible_fleet_types=["NARROWBODY"],
        )
        counterparty = fx.do_create_counterparty(
            api,
            counterparty_code="DLRC",
            legal_name="Dealer C Bank NA",
            credit_rating="A",
        )
        fx.do_create_published_forecast(api)
        program = fx.do_create_program(
            api,
            policy["id"],
            program_code="HP-SWAPONLY",
            route_groups=["DOMESTIC_SHORT"],
            target_coverage_pct=30.00,
        )
        program = fx.do_size_program(api, program["id"])
        return program, counterparty

    def test_a_collar_is_refused_under_a_swap_only_policy_and_no_row_appears(self, api):
        """PRD §3.4: "An `instrument_type` that is not a member of the governing
        policy's `permitted_instrument_types` is rejected with
        `ERR_INSTRUMENT_TYPE_NOT_PERMITTED`."

        PRD §2.5: "**Permitted instrument type** on instrument proposal,
        otherwise `ERR_INSTRUMENT_TYPE_NOT_PERMITTED` (422)." The check runs at
        proposal, so the collar never becomes a child row at all.

        Design: Corner/validations/collar_rejected_when_policy_permits_swaps_only
        """
        program, counterparty = self._swap_only_policy_with_a_sized_programme(api)

        validate_error(
            api.create_hedge_instrument(
                program["id"],
                f.collar_payload(
                    counterparty["id"],
                    program["version"],
                    notional_gallons=1000000,
                    floor_strike_usd_per_gal=2.4000,
                    cap_strike_usd_per_gal=2.9000,
                    maturity_month="2027-03",
                ),
                headers=ANALYST,
            ),
            ERR_INSTRUMENT_TYPE_NOT_PERMITTED,
            422,
        )

        rows, meta = validate_paginated(
            api.list_program_instruments(program["id"], headers=ANALYST)
        )
        assert len(rows) == 0
        assert meta["total_count"] == 0

    def test_a_permitted_swap_on_the_same_endpoint_still_succeeds(self, api):
        """PRD §3.4: creation "opens the instrument at `trade_status` `PROPOSED`
        and `accounting_status` `UNDESIGNATED`, writes `delta_factor` from the
        type — 1.00 for a `SWAP`, 0.65 for a `COLLAR`, 0.50 for a `CALL_OPTION` —
        and writes `delta_adjusted_gallons` as `notional_gallons` multiplied by
        `delta_factor`, rounded to two decimal places."

        Design: Corner/validations/collar_rejected_when_policy_permits_swaps_only
        """
        program, counterparty = self._swap_only_policy_with_a_sized_programme(api)
        validate_error(
            api.create_hedge_instrument(
                program["id"],
                f.collar_payload(
                    counterparty["id"],
                    program["version"],
                    notional_gallons=1000000,
                    floor_strike_usd_per_gal=2.4000,
                    cap_strike_usd_per_gal=2.9000,
                    maturity_month="2027-03",
                ),
                headers=ANALYST,
            ),
            ERR_INSTRUMENT_TYPE_NOT_PERMITTED,
            422,
        )

        data = validate_success(
            api.create_hedge_instrument(
                program["id"],
                f.swap_payload(
                    counterparty["id"],
                    program["version"],
                    notional_gallons=1000000,
                    strike_usd_per_gal=2.5000,
                    maturity_month="2027-03",
                ),
                headers=ANALYST,
            ),
            201,
        )
        assert data["instrument_type"] == "SWAP"
        assert_instrument_status(
            data, trade_status="PROPOSED", accounting_status="UNDESIGNATED"
        )
        assert_instrument_ledgers(
            data, delta_factor=1.00, delta_adjusted_gallons=1000000.00
        )


class TestConcentrationWaiver:
    @staticmethod
    def _active_programme_over_a_twenty_percent_cap(api):
        return fx.setup_active_program_with_proposed_swap(
            api,
            single_forecast=True,
            policy_overrides=dict(
                policy_code="FY27-CONC",
                max_coverage_pct=60.00,
                min_coverage_pct=5.00,
                max_single_counterparty_pct=20.00,
                max_earnings_volatility_usd=500000.00,
                eligible_fleet_types=["NARROWBODY"],
            ),
            counterparty_overrides=dict(
                counterparty_code="DLRC",
                legal_name="Dealer C Bank NA",
                credit_rating="A",
            ),
            program_overrides=dict(
                program_code="HP-CONC",
                route_groups=["DOMESTIC_SHORT"],
                target_coverage_pct=30.00,
            ),
            swap_overrides=dict(
                notional_gallons=1000000,
                strike_usd_per_gal=2.5000,
                maturity_month="2027-03",
            ),
        )

    def test_a_merely_requested_waiver_does_not_unlock_the_concentration_gate(self, api):
        """PRD §3.4: "If the rounded share exceeds the policy's
        `max_single_counterparty_pct` and no `APPROVED` policy exception with
        `reason_code` `COUNTERPARTY_CONCENTRATION` references this instrument,
        the execution is rejected with `ERR_EXCEPTION_REQUIRED`."

        PRD §3.9: "A new exception opens in `REQUESTED` status with `origin`
        `MANUAL`, `requested_by_user_id` from the caller's `X-User-ID`, and
        `decided_by_user_id` and `decided_at` null. When `hedge_program_id` is
        not null, creation also increments the `open_exception_count` of the
        policy governing that programme by one".

        A 1,000,000-gallon share of a 4,400,000-gallon basis is 22.73 per cent
        against a 20.00 per cent cap.

        Design: Corner/validations/concentration_breach_needs_approved_exception_before_execute_succeeds
        """
        ctx = self._active_programme_over_a_twenty_percent_cap(api)
        instrument_id = ctx["instrument"]["id"]

        validate_error(
            api.execute_hedge_instrument(
                instrument_id, headers=make_treasury_headers(TRM_1)
            ),
            ERR_EXCEPTION_REQUIRED,
            422,
        )

        exception = validate_success(
            api.create_policy_exception(
                f.policy_exception_payload(
                    "COUNTERPARTY_CONCENTRATION",
                    "Single-dealer concentration of 22.73 percent accepted for this program period.",
                    hedge_program_id=ctx["program"]["id"],
                    hedge_instrument_id=instrument_id,
                    requested_limit_value=22.73,
                ),
                headers=make_analyst_headers(ANALYST_1),
            ),
            201,
        )
        assert exception["origin"] == "MANUAL"
        assert exception["requested_by_user_id"] == ANALYST_1
        assert_undecided_exception(exception)

        policy = fx.read_policy(api, ctx["policy"]["id"])
        assert policy["open_exception_count"] == 1

        # Still only REQUESTED, so the gate is untouched.
        validate_error(
            api.execute_hedge_instrument(
                instrument_id, headers=make_treasury_headers(TRM_1)
            ),
            ERR_EXCEPTION_REQUIRED,
            422,
        )

    def test_the_approved_waiver_flips_the_identical_execute_call_to_success(self, api):
        """PRD §3.9: "Trade execution tolerates a single-counterparty
        concentration above `max_single_counterparty_pct` only when an `APPROVED`
        exception with `reason_code` `COUNTERPARTY_CONCENTRATION` references that
        instrument."

        PRD §3.9: both decisions "decrement by one the `open_exception_count` of
        the policy governing the exception's `hedge_program_id` when that
        reference is not null".

        PRD §3.4: step one is "`notional_gallons` multiplied by a per-gallon
        margin rate that is 0.06 for a `SWAP`", and with no prior exposure the
        add-on rate is "0.00 below 50 percent", so the requirement is 60,000.00.

        Design: Corner/validations/concentration_breach_needs_approved_exception_before_execute_succeeds
        """
        ctx = self._active_programme_over_a_twenty_percent_cap(api)
        instrument_id = ctx["instrument"]["id"]
        validate_error(
            api.execute_hedge_instrument(
                instrument_id, headers=make_treasury_headers(TRM_1)
            ),
            ERR_EXCEPTION_REQUIRED,
            422,
        )

        exception = fx.do_request_exception(
            api,
            "COUNTERPARTY_CONCENTRATION",
            "Single-dealer concentration of 22.73 percent accepted for this program period.",
            headers=make_analyst_headers(ANALYST_1),
            hedge_program_id=ctx["program"]["id"],
            hedge_instrument_id=instrument_id,
            requested_limit_value=22.73,
        )
        decided = validate_success(
            api.approve_policy_exception(
                exception["id"],
                f.decision_payload("Concentration waiver granted by the risk committee."),
                headers=ADMIN,
            )
        )
        assert decided["status"] == "APPROVED"
        assert decided["decided_by_user_id"] == "u_admin_1"

        executed = validate_success(
            api.execute_hedge_instrument(
                instrument_id, headers=make_treasury_headers(TRM_1)
            )
        )
        assert_instrument_status(executed, trade_status="EXECUTED")
        assert_instrument_ledgers(
            executed,
            margin_requirement_usd=60000.00,
            delta_adjusted_gallons=1000000.00,
        )

        policy = fx.read_policy(api, ctx["policy"]["id"])
        assert policy["open_exception_count"] == 0


class TestZeroUpliftOnReconciliation:
    def test_reporting_no_uplift_flown_is_refused_rather_than_computed(self, api):
        """PRD §3.8: "The `FuelOpsController` supplies `actual_uplift_gallons`
        and `actual_block_minutes`; the actual uplift must be strictly greater
        than zero, otherwise `ERR_ZERO_UPLIFT`, and no greater than the leg's
        `uplift_cap_gallons`, otherwise `ERR_TANKERING_WEIGHT_LIMIT`."

        PRD §2.5: "**Strictly positive uplift.** `requested_uplift_gallons` on
        directive creation and revision, and `actual_uplift_gallons` on
        reconciliation, must all be greater than zero, otherwise
        `ERR_ZERO_UPLIFT` (422)."

        Design: Corner/validations/reconcile_with_zero_actual_uplift_returns_422_zero_uplift
        """
        ctx = fx.setup_loaded_directive(
            api, 3000, policy_overrides=dict(policy_code="FY27-TANK")
        )
        directive_id = ctx["directive"]["id"]

        validate_error(
            api.reconcile_tankering_directive(
                directive_id,
                f.reconcile_directive_payload(0, 250),
                headers=OPS,
            ),
            ERR_ZERO_UPLIFT,
            422,
        )

        after = fx.read_directive(api, directive_id)
        assert after["status"] == "EXECUTED"
        assert after["reconciled_burn_penalty_gallons"] is None
        assert after["reconciled_net_savings_usd"] is None
        assert after["savings_variance_usd"] is None
        assert_planned_economics(
            after,
            planned_burn_penalty_gallons=368.9,
            planned_net_savings_usd=978.82,
        )
        assert_pinned_prices(after, 2.4700, 3.1000, "ORD-2027-A")

    def test_the_refused_reconciliation_leaves_the_loaded_gallons_where_they_were(
        self, api
    ):
        """PRD §3.8: "Reconciliation also trues up the gallon ledger: the origin
        station's `inventory_gallons` is adjusted by the requested uplift less
        the actual uplift".

        Because the request never got that far, the station keeps the 497,000
        gallons loading left behind — PRD §3.2 puts that at 4.97 days of cover
        against 100,000 daily liftings, which is `WATCH`.

        PRD §3.8: "Both values are written onto the leg, whose `version` is
        incremented by one", so the leg's flown fields must still be null.

        Design: Corner/validations/reconcile_with_zero_actual_uplift_returns_422_zero_uplift
        """
        ctx = fx.setup_loaded_directive(
            api, 3000, policy_overrides=dict(policy_code="FY27-TANK")
        )

        validate_error(
            api.reconcile_tankering_directive(
                ctx["directive"]["id"],
                f.reconcile_directive_payload(0, 250),
                headers=OPS,
            ),
            ERR_ZERO_UPLIFT,
            422,
        )

        origin = fx.read_station(api, ctx["origin"]["id"])
        assert_station_supply(
            origin,
            inventory_gallons=497000,
            days_cover=4.97,
            supply_posture="WATCH",
        )

        leg = fx.read_flight_leg(api, ctx["leg"]["id"])
        assert leg["actual_uplift_gallons"] is None
        assert leg["actual_block_minutes"] is None


class TestUneconomicTankeringWaiver:
    @staticmethod
    def _reversed_price_pair_with_a_proposed_directive(api):
        """ORD is the dear station and DFW the cheap one, so uplift loses money."""
        fx.set_clock(api, fx.TANKERING_CLOCK)
        policy = fx.do_create_policy(api, policy_code="FY27-TANK")
        origin = fx.do_create_station(
            api,
            iata_code="ORD",
            name="Chicago OHare",
            into_plane_fee_usd_per_gal=0.0800,
            avg_daily_liftings_gallons=80000,
        )
        destination = fx.do_create_station(
            api,
            iata_code="DFW",
            name="Dallas Fort Worth",
            into_plane_fee_usd_per_gal=0.0450,
            avg_daily_liftings_gallons=100000,
        )
        fx.do_create_contract(
            api,
            origin["id"],
            contract_ref="ORD-2027",
            index_price_usd_per_gal=2.9000,
            differential_usd_per_gal=0.1200,
            term_start_date="2027-01-01",
            term_end_date="2027-12-31",
        )
        fx.do_create_contract(
            api,
            destination["id"],
            contract_ref="DFW-2027",
            index_price_usd_per_gal=2.4000,
            differential_usd_per_gal=0.0250,
            term_start_date="2027-01-01",
            term_end_date="2027-12-31",
        )
        fx.do_adjust_inventory(
            api, origin["id"], 400000, "Opening physical stock at the origin station."
        )
        leg = fx.do_create_leg(
            api,
            origin["id"],
            destination["id"],
            flight_number="FU500",
            departure_date="2027-02-10",
            planned_burn_gallons=15000,
            tank_capacity_gallons=26500,
            landing_weight_lbs=130000,
            max_landing_weight_lbs=205000,
        )
        directive = fx.do_propose_directive(api, leg["id"], 3000)
        return {"policy": policy, "origin": origin, "leg": leg, "directive": directive}

    def test_a_loss_making_uplift_is_refused_at_approval(self, api):
        """PRD §3.8: "And `planned_net_savings_usd` must be strictly greater than
        zero, unless an `APPROVED` policy exception with `reason_code`
        `TANKERING_UNECONOMIC` references this directive; failing both, the
        approval is rejected with `ERR_TANKERING_NOT_ECONOMIC`."

        PRD §3.8: "Gross savings are the uplift multiplied by the destination
        price per gallon less the origin price per gallon, rounded to two decimal
        places. The penalty cost is the burn penalty in gallons multiplied by the
        *origin* price per gallon, rounded to two decimal places. Net savings are
        the gross savings less the penalty cost".

        Uplifting 3,000 gallons at 3.1000 to burn them off at 2.4700 gives
        -1,890.00 of gross saving; a 368.9-gallon penalty at the 3.1000 origin
        price costs 1,143.59; the net is -3,033.59.

        Design: Corner/validations/uneconomic_tankering_blocked_then_waived_by_approved_exception
        """
        ctx = self._reversed_price_pair_with_a_proposed_directive(api)

        assert_planned_economics(
            ctx["directive"],
            planned_burn_penalty_gallons=368.9,
            planned_gross_savings_usd=-1890.00,
            planned_penalty_cost_usd=1143.59,
            planned_net_savings_usd=-3033.59,
        )

        validate_error(
            api.approve_tankering_directive(ctx["directive"]["id"], headers=OPS),
            ERR_TANKERING_NOT_ECONOMIC,
            422,
        )

    def test_a_waiver_naming_only_the_directive_unlocks_approval_and_moves_no_policy_counter(
        self, api
    ):
        """PRD §3.9: "Directive approval tolerates non-positive
        `planned_net_savings_usd` only when an `APPROVED` exception with
        `reason_code` `TANKERING_UNECONOMIC` references that directive."

        PRD §3.9: "When `hedge_program_id` is not null, creation also increments
        the `open_exception_count` of the policy governing that programme by
        one" — this waiver names no programme, so the counter never moves.

        PRD §3.8: "Approval then pins prices: `pinned_origin_price_usd_per_gal`
        and `pinned_destination_price_usd_per_gal` are frozen from the two active
        contracts' all-in prices as of the approval instant, and
        `pinned_origin_contract_ref` records the `contract_ref` of the origin
        contract selected."

        Design: Corner/validations/uneconomic_tankering_blocked_then_waived_by_approved_exception
        """
        ctx = self._reversed_price_pair_with_a_proposed_directive(api)
        directive_id = ctx["directive"]["id"]
        validate_error(
            api.approve_tankering_directive(directive_id, headers=OPS),
            ERR_TANKERING_NOT_ECONOMIC,
            422,
        )

        exception = validate_success(
            api.create_policy_exception(
                f.policy_exception_payload(
                    "TANKERING_UNECONOMIC",
                    "Uplift required to protect a downline fuel shortage at the destination station.",
                    tankering_directive_id=directive_id,
                    requested_limit_value=-3033.59,
                ),
                headers=OPS,
            ),
            201,
        )
        assert exception["status"] == "REQUESTED"
        assert exception["hedge_program_id"] is None
        assert exception["tankering_directive_id"] == directive_id

        approved_exception = fx.do_approve_exception(api, exception["id"])
        assert approved_exception["status"] == "APPROVED"

        approved = validate_success(
            api.approve_tankering_directive(directive_id, headers=OPS)
        )
        assert approved["status"] == "APPROVED"
        assert approved["approved_by_user_id"] == "u_ops_1"
        assert_planned_economics(
            approved,
            planned_burn_penalty_gallons=368.9,
            planned_gross_savings_usd=-1890.00,
            planned_penalty_cost_usd=1143.59,
            planned_net_savings_usd=-3033.59,
        )
        assert_pinned_prices(approved, 3.1000, 2.4700, "ORD-2027")

        policy = fx.read_policy(api, ctx["policy"]["id"])
        assert policy["open_exception_count"] == 0
