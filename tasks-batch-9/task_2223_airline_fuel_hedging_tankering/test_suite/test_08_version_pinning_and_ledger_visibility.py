"""Optimistic pins on the three parented creates, and immediate consistency.

Each of the three pins is invalidated by a write nothing in the request refers
to — a sibling instrument, a credit re-rating, a reconciliation — and in every
case the refusal is the pin rather than a state conflict, because the same
payload succeeds the moment the parent is re-read. The last group pins the other
half of that bargain: what one write cascades to is visible on the next read.
"""

from test_helpers import (
    ADMIN,
    ANALYST,
    ERR_INSTRUMENT_INVALID_TRADE_STATE,
    ERR_STALE_VERSION,
    OPS,
    TREASURY,
    assert_counterparty_credit,
    assert_instrument_ledgers,
    assert_money,
    assert_pagination_meta,
    assert_program_coverage,
    assert_request_meta,
    assert_whole_gallons,
    factories as f,
    fixtures as fx,
    ids_of,
    validate_error,
    validate_paginated,
    validate_success,
)

CORNER_POLICY = dict(
    policy_code="FY27-CORNER",
    min_coverage_pct=5.00,
    max_single_counterparty_pct=100.00,
    max_earnings_volatility_usd=500000.00,
    eligible_fleet_types=["NARROWBODY"],
)
CORNER_DEALER = dict(
    counterparty_code="DLRC", legal_name="Dealer C Bank NA", credit_rating="A"
)
CORNER_PROGRAM = dict(
    program_code="HP-CORNER",
    route_groups=["DOMESTIC_SHORT"],
    target_coverage_pct=30.00,
)
CORNER_SWAP = dict(
    notional_gallons=1000000, strike_usd_per_gal=2.5000, maturity_month="2027-03"
)


class TestProgramVersionPinOnInstrumentProposal:
    @staticmethod
    def _sized_program_and_its_dealer(api):
        return fx.setup_single_forecast_sized_program(
            api,
            policy_overrides=CORNER_POLICY,
            counterparty_overrides=CORNER_DEALER,
            program_overrides=CORNER_PROGRAM,
        )

    @staticmethod
    def _second_swap(counterparty_id, pinned_version):
        return f.swap_payload(
            counterparty_id,
            pinned_version,
            notional_gallons=400000,
            strike_usd_per_gal=2.5500,
            maturity_month="2027-03",
        )

    def test_replaying_the_version_the_first_instrument_consumed_is_refused(self, api):
        """PRD §2.6: "Proposing a hedge instrument under a programme (`POST
        /fuel/hedge-programs/{id}/instruments`) requires
        `expected_hedge_program_version`, carrying the client's last observed
        `version` of that `HedgeProgram`. If the programme's current `version`
        differs, the create is rejected with `ERR_STALE_VERSION` (412). Adding a
        second instrument to a programme is perfectly legitimate, so no state
        precondition would catch this".

        The first proposal itself advances the programme, so the client's own
        successful write is what invalidated its pin.

        Design: Corner/cross_cutting_complexity_layers/stale_program_version_blocks_a_second_instrument_until_refreshed
        """
        ctx = self._sized_program_and_its_dealer(api)
        pinned = ctx["program"]["version"]

        first = validate_success(
            api.create_hedge_instrument(
                ctx["program"]["id"],
                f.swap_payload(ctx["counterparty"]["id"], pinned, **CORNER_SWAP),
                headers=ANALYST,
            ),
            201,
        )
        assert_whole_gallons(
            first["notional_gallons"], 1000000, "notional_gallons"
        )

        validate_error(
            api.create_hedge_instrument(
                ctx["program"]["id"],
                self._second_swap(ctx["counterparty"]["id"], pinned),
                headers=ANALYST,
            ),
            ERR_STALE_VERSION,
            412,
        )

    def test_the_refused_proposal_wrote_nothing_and_the_refreshed_pin_is_accepted(
        self, api
    ):
        """PRD §3.4: "It also increments the parent programme's
        `open_instrument_count` by one, recomputes the programme's
        `planned_coverage_pct_delta`, and increments the programme's `version` by
        one."

        PRD §3.4: "On the notional basis, `hedged_gallons` is the sum of
        `notional_gallons` over the programme's children whose `trade_status` is
        `EXECUTED`" — neither swap is executed, so the notional ledger is still
        empty while the planned measure reads 1,000,000 over 4,400,000, or 22.73
        percent.

        Design: Corner/cross_cutting_complexity_layers/stale_program_version_blocks_a_second_instrument_until_refreshed
        """
        ctx = self._sized_program_and_its_dealer(api)
        pinned = ctx["program"]["version"]
        validate_success(
            api.create_hedge_instrument(
                ctx["program"]["id"],
                f.swap_payload(ctx["counterparty"]["id"], pinned, **CORNER_SWAP),
                headers=ANALYST,
            ),
            201,
        )
        validate_error(
            api.create_hedge_instrument(
                ctx["program"]["id"],
                self._second_swap(ctx["counterparty"]["id"], pinned),
                headers=ANALYST,
            ),
            ERR_STALE_VERSION,
            412,
        )

        program = fx.read_program(api, ctx["program"]["id"])
        assert program["version"] == pinned + 1
        assert program["open_instrument_count"] == 1
        assert_program_coverage(
            program,
            consumption_basis_gallons=4400000,
            hedged_gallons=0,
            planned_coverage_pct_delta=22.73,
        )

        second = validate_success(
            api.create_hedge_instrument(
                ctx["program"]["id"],
                self._second_swap(
                    ctx["counterparty"]["id"], program["version"]
                ),
                headers=ANALYST,
            ),
            201,
        )
        assert_whole_gallons(
            second["notional_gallons"], 400000, "notional_gallons"
        )

        rows, meta = validate_paginated(
            api.list_program_instruments(
                ctx["program"]["id"], headers=ANALYST, params={"trade_status": "PROPOSED"}
            )
        )
        assert meta["total_count"] == 2
        assert len(rows) == 2


class TestCounterpartyVersionPinOnCollateralPosting:
    @staticmethod
    def _executed_swap_and_its_dealer(api):
        return fx.setup_active_program_with_executed_swap(
            api,
            single_forecast=True,
            policy_overrides=CORNER_POLICY,
            counterparty_overrides=CORNER_DEALER,
            program_overrides=CORNER_PROGRAM,
            swap_overrides=CORNER_SWAP,
        )

    def test_a_credit_re_rating_alone_invalidates_a_pinned_counterparty_version(
        self, api
    ):
        """PRD §2.4: "Recomputation of a derived field counts as a mutation: when
        a trade execution moves a counterparty's credit ledger, the
        counterparty's `version` advances and its `updated_at` is refreshed even
        though no client sent a field for it."

        PRD §2.6: "Raising a manual collateral requirement under a counterparty
        (`POST /fuel/counterparties/{id}/collateral-postings`) requires
        `expected_counterparty_version`, carrying the client's last observed
        `version` of that `Counterparty`. A mismatch with the counterparty's
        current `version` is rejected with `ERR_STALE_VERSION` (412)."

        The review only re-rates the dealer from A to BBB — it neither changes the
        trade nor bars further postings — yet it moves the version the posting
        quoted.

        Design: Corner/cross_cutting_complexity_layers/stale_counterparty_version_blocks_a_collateral_posting_after_credit_review
        """
        ctx = self._executed_swap_and_its_dealer(api)
        pinned = fx.read_counterparty(api, ctx["counterparty"]["id"])["version"]

        reviewed = fx.do_credit_review(
            api,
            ctx["counterparty"]["id"],
            "BBB",
            review_note="Quarterly re-rating after the dealer's earnings release.",
        )
        assert reviewed["credit_rating"] == "BBB"
        assert reviewed["status"] == "APPROVED"
        assert reviewed["version"] == pinned + 1

        validate_error(
            api.create_collateral_posting(
                ctx["counterparty"]["id"],
                f.collateral_posting_payload(ctx["instrument"]["id"], pinned, "CASH"),
                headers=ADMIN,
            ),
            ERR_STALE_VERSION,
            412,
        )

    def test_the_refused_posting_created_nothing_and_the_refreshed_pin_is_accepted(
        self, api
    ):
        """PRD §3.5: "Creation opens the row in `REQUIRED` status with `origin`
        `MANUAL` and `posted_amount_usd` at 0, and freezes `required_amount_usd`
        at that moment as the trade's `margin_requirement_usd` less its
        `collateral_posted_usd`, floored at zero so a fully collateralised trade
        yields a requirement of 0.00."

        PRD §3.5: "Creation also increments the counterparty's
        `open_margin_call_count` by one and its `version` by one, and leaves
        `posted_at` and `returned_at` null."

        Design: Corner/cross_cutting_complexity_layers/stale_counterparty_version_blocks_a_collateral_posting_after_credit_review
        """
        ctx = self._executed_swap_and_its_dealer(api)
        pinned = fx.read_counterparty(api, ctx["counterparty"]["id"])["version"]
        fx.do_credit_review(
            api,
            ctx["counterparty"]["id"],
            "BBB",
            review_note="Quarterly re-rating after the dealer's earnings release.",
        )
        validate_error(
            api.create_collateral_posting(
                ctx["counterparty"]["id"],
                f.collateral_posting_payload(ctx["instrument"]["id"], pinned, "CASH"),
                headers=ADMIN,
            ),
            ERR_STALE_VERSION,
            412,
        )

        counterparty = fx.read_counterparty(api, ctx["counterparty"]["id"])
        assert_counterparty_credit(
            counterparty, posted_collateral_usd=0, open_margin_call_count=0
        )
        _rows, empty_meta = validate_paginated(
            api.list_counterparty_collateral_postings(
                counterparty["id"], headers=TREASURY
            )
        )
        assert empty_meta["total_count"] == 0

        posting = validate_success(
            api.create_collateral_posting(
                counterparty["id"],
                f.collateral_posting_payload(
                    ctx["instrument"]["id"], counterparty["version"], "CASH"
                ),
                headers=ADMIN,
            ),
            201,
        )
        assert posting["status"] == "REQUIRED"
        assert posting["posted_at"] is None
        assert posting["returned_at"] is None
        assert_money(posting["required_amount_usd"], 60000.00, "required_amount_usd")

        rows, meta = validate_paginated(
            api.list_counterparty_collateral_postings(
                counterparty["id"], headers=TREASURY, params={"status": "REQUIRED"}
            )
        )
        assert meta["total_count"] == 1
        assert ids_of(rows) == [posting["id"]]


class TestFlightLegVersionPinOnDirectiveProposal:
    @staticmethod
    def _reconciled_directive_and_the_version_it_left_behind(api):
        ctx = fx.setup_loaded_directive(
            api, 3000, policy_overrides=dict(policy_code="FY27-TANK")
        )
        ctx["stale_leg_version"] = fx.read_flight_leg(api, ctx["leg"]["id"])["version"]
        ctx["directive"] = fx.do_reconcile_directive(
            api, ctx["directive"]["id"], 3000, 210
        )
        return ctx

    def test_reconciliation_invalidates_a_leg_version_read_before_it(self, api):
        """PRD §2.6: "Proposing a tankering directive on a flight leg (`POST
        /fuel/flight-legs/{id}/tankering-directives`) requires
        `expected_flight_leg_version`, carrying the client's last observed
        `version` of that `FlightLeg`. A mismatch with the leg's current
        `version` is rejected with `ERR_STALE_VERSION` (412)."

        PRD §3.8: "The `FuelOpsController` supplies `actual_uplift_gallons` and
        `actual_block_minutes`; the actual uplift must be strictly greater than
        zero, otherwise `ERR_ZERO_UPLIFT`, and no greater than the leg's
        `uplift_cap_gallons`, otherwise `ERR_TANKERING_WEIGHT_LIMIT`. Both values
        are written onto the leg, whose `version` is incremented by one."

        Design: Corner/cross_cutting_complexity_layers/stale_flight_leg_version_blocks_a_follow_up_directive_after_reconciliation
        """
        ctx = self._reconciled_directive_and_the_version_it_left_behind(api)

        validate_error(
            api.create_tankering_directive(
                ctx["leg"]["id"],
                f.tankering_directive_payload(2000, ctx["stale_leg_version"]),
                headers=ANALYST,
            ),
            ERR_STALE_VERSION,
            412,
        )

        assert fx.read_directive(api, ctx["directive"]["id"])["status"] == "RECONCILED"
        leg = fx.read_flight_leg(api, ctx["leg"]["id"])
        assert_whole_gallons(
            leg["actual_uplift_gallons"], 3000, "actual_uplift_gallons"
        )
        assert leg["actual_block_minutes"] == 210
        assert leg["version"] == ctx["stale_leg_version"] + 1

    def test_the_refreshed_pin_opens_a_second_directive_on_the_same_leg(self, api):
        """PRD §3.8: "As a system side effect, any earlier directive on the same
        leg whose `status` is `PROPOSED` or `NEEDS_REVISION` is displaced —
        `PROPOSED → SUPERSEDED` and `NEEDS_REVISION → SUPERSEDED` respectively —
        and has its `version` incremented by one; the new directive is the only
        live one."

        PRD §3.8: "Creating a directive opens it in `PROPOSED` status with
        `revision_count` 0, `proposed_by_user_id` from the caller's `X-User-ID`,
        `approved_by_user_id` null".

        A `RECONCILED` directive is outside the displaced set, so the leg ends
        with one reconciled directive and one live proposal.

        Design: Corner/cross_cutting_complexity_layers/stale_flight_leg_version_blocks_a_follow_up_directive_after_reconciliation
        """
        ctx = self._reconciled_directive_and_the_version_it_left_behind(api)
        validate_error(
            api.create_tankering_directive(
                ctx["leg"]["id"],
                f.tankering_directive_payload(2000, ctx["stale_leg_version"]),
                headers=ANALYST,
            ),
            ERR_STALE_VERSION,
            412,
        )

        refreshed = fx.read_flight_leg(api, ctx["leg"]["id"])["version"]
        follow_up = validate_success(
            api.create_tankering_directive(
                ctx["leg"]["id"],
                f.tankering_directive_payload(2000, refreshed),
                headers=ANALYST,
            ),
            201,
        )
        assert follow_up["status"] == "PROPOSED"
        assert follow_up["revision_count"] == 0
        assert_whole_gallons(
            follow_up["requested_uplift_gallons"], 2000, "requested_uplift_gallons"
        )

        rows, meta = validate_paginated(
            api.list_leg_tankering_directives(
                ctx["leg"]["id"], headers=OPS, params={"status": "PROPOSED"}
            )
        )
        assert meta["total_count"] == 1
        assert ids_of(rows) == [follow_up["id"]]
        assert fx.read_directive(api, ctx["directive"]["id"])["status"] == "RECONCILED"


class TestImmediateVisibilityOfExecutionLedgers:
    @staticmethod
    def _active_program_with_a_proposed_swap(api):
        return fx.setup_active_program_with_proposed_swap(
            api,
            single_forecast=True,
            policy_overrides=CORNER_POLICY,
            counterparty_overrides=CORNER_DEALER,
            program_overrides=CORNER_PROGRAM,
            swap_overrides=CORNER_SWAP,
        )

    def test_the_execute_response_already_carries_the_margin_it_computed(self, api):
        """PRD §3.4: "Step one computes a base margin that does not depend on
        exposure at all: `notional_gallons` multiplied by a per-gallon margin rate
        that is 0.06 for a `SWAP`, 0.04 for a `COLLAR` and 0.02 for a
        `CALL_OPTION`".

        PRD §2.2: "The `api_request_id` is a server-generated unique identifier
        for the request that starts with `req_`."

        A 1,000,000-gallon swap at 0.06 per gallon is 60,000.00, and the exposure
        percentage the add-on tier reads is 0.00 before this trade, so the add-on
        rate is 0.00 and the requirement is the base itself.

        Design: Corner/consistency_model/execute_makes_every_derived_ledger_visible_in_the_same_request
        """
        ctx = self._active_program_with_a_proposed_swap(api)

        response = api.execute_hedge_instrument(
            ctx["instrument"]["id"], headers=TREASURY
        )
        data = validate_success(response)
        body = response.json()

        assert body["response_type"] == "object"
        assert_request_meta(body)
        assert data["trade_status"] == "EXECUTED"
        assert data["executed_at"] is not None
        assert_instrument_ledgers(
            data,
            margin_requirement_usd=60000.00,
            delta_adjusted_gallons=1000000.00,
            delta_factor=1.00,
        )

    def test_the_next_reads_show_the_cascade_with_no_intervening_write(self, api):
        """PRD §3.4: "Execution then cascades. It writes the new
        `margin_requirement_usd`, adds that amount to the counterparty's
        `utilized_credit_usd` and recomputes the counterparty's `utilization_pct`
        and `credit_posture`; it adds the trade's `notional_gallons` to the
        programme's `hedged_gallons` and the trade's `delta_adjusted_gallons` to
        the programme's `delta_adjusted_gallons` and recomputes all three
        coverage percentages".

        PRD §2.3: "Both are echoed back in the `meta` object of the envelope
        alongside `total_count` (the number of items matching the query before
        pagination) and `has_more` (true when items remain beyond the current
        window)."

        60,000.00 against a 2,000,000.00 limit is 3.00 percent utilisation, and
        1,000,000 gallons over a 4,400,000-gallon basis is 22.73 percent on both
        coverage bases because a swap's delta factor is 1.00.

        Design: Corner/consistency_model/execute_makes_every_derived_ledger_visible_in_the_same_request
        """
        ctx = self._active_program_with_a_proposed_swap(api)
        instrument = fx.do_execute_instrument(api, ctx["instrument"]["id"])

        counterparty = fx.read_counterparty(api, ctx["counterparty"]["id"])
        assert_counterparty_credit(
            counterparty,
            utilized_credit_usd=60000.00,
            utilization_pct=3.00,
            credit_posture="NORMAL",
            posted_collateral_usd=0,
        )

        program = fx.read_program(api, ctx["program"]["id"])
        assert_program_coverage(
            program,
            hedged_gallons=1000000,
            delta_adjusted_gallons=1000000.00,
            coverage_pct_notional=22.73,
            coverage_pct_delta=22.73,
        )
        assert program["compliance_posture"] == "COMPLIANT"

        response = api.list_hedge_instruments(
            headers=TREASURY,
            params={
                "counterparty_id": ctx["counterparty"]["id"],
                "trade_status": "EXECUTED",
            },
        )
        rows, meta = validate_paginated(response)
        assert response.json()["response_type"] == "array"
        assert_pagination_meta(
            meta, total_count=1, limit=10, offset=0, has_more=False
        )
        assert ids_of(rows) == [instrument["id"]]

    def test_a_second_execute_reports_the_error_envelope(self, api):
        """PRD §3.4: "Executing a trade that is not `PROPOSED` yields
        `ERR_INSTRUMENT_INVALID_TRADE_STATE`."

        PRD §2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."

        Design: Corner/consistency_model/execute_makes_every_derived_ledger_visible_in_the_same_request
        """
        ctx = self._active_program_with_a_proposed_swap(api)
        fx.do_execute_instrument(api, ctx["instrument"]["id"])

        response = api.execute_hedge_instrument(
            ctx["instrument"]["id"], headers=TREASURY
        )
        error = validate_error(response, ERR_INSTRUMENT_INVALID_TRADE_STATE, 409)
        body = response.json()

        assert body["response_type"] == "error"
        assert_request_meta(body)
        assert error["message"].strip()
        assert set(body["meta"]) == {"api_request_id", "api_request_timestamp"}
