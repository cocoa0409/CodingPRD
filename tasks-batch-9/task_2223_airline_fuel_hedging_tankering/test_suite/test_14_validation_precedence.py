"""Requests that break two rules at once, and the one answer each must give.

Each scenario fires a call that is false on two counts, checks that the higher
ladder rung answers, and then removes that rung so the masked condition can
surface — proving it was live all along and not merely absent.
"""

from test_helpers import (
    ADMIN,
    ANALYST,
    ERR_CONTRACT_BUFFER_VIOLATION,
    ERR_CONTRACT_TERM_OVERLAP,
    ERR_COVERAGE_LIMIT_EXCEEDED,
    ERR_DUPLICATE_CONTRACT_REF,
    ERR_NO_ACTIVE_SUPPLY_CONTRACT,
    ERR_PROGRAM_NOT_ACTIVE,
    ERR_TANKERING_WEIGHT_LIMIT,
    OPS,
    TREASURY,
    assert_counterparty_credit,
    assert_gallon_tenths,
    assert_instrument_status,
    assert_nothing_pinned,
    assert_pct,
    assert_price,
    assert_program_coverage,
    assert_whole_gallons,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_paginated,
)

#: The 8,000,000-gallon swap that would take delta coverage to 72.7272... percent
#: of an 11,000,000-gallon basis, well past the 60.00 ceiling.
OVERSIZED_SWAP = dict(
    notional_gallons=8000000,
    strike_usd_per_gal=2.4000,
    maturity_month="2027-03",
)

#: The two clock instants of the expiring-contract scenario.
PROPOSAL_CLOCK = "2027-02-10T00:00:00Z"
POST_EXPIRY_CLOCK = "2027-03-15T00:00:00Z"

#: The overlapping and the well-separated candidate terms, both reusing the ref.
OVERLAPPING_TERM = dict(term_start_date="2027-03-01", term_end_date="2027-04-30")
SEPARATED_TERM = dict(term_start_date="2027-07-08", term_end_date="2027-12-31")


class TestProgramStateGateBeatsCoverageCeiling:
    @staticmethod
    def _submitted_program_carrying_an_oversized_swap(api):
        ctx = fx.setup_sized_program(
            api,
            policy_overrides=dict(
                policy_code="FY27-PP1", max_single_counterparty_pct=100.00
            ),
            counterparty_overrides=dict(
                counterparty_code="DLRA",
                legal_name="Dealer A Bank NA",
                credit_rating="A",
                credit_limit_usd=2000000.00,
            ),
            program_overrides=dict(program_code="HP-PP1", target_coverage_pct=55.00),
        )
        ctx["instrument"] = fx.do_propose_swap(
            api,
            ctx["program"]["id"],
            ctx["counterparty"]["id"],
            **OVERSIZED_SWAP,
        )
        ctx["program"] = fx.do_submit_program(api, ctx["program"]["id"])
        return ctx

    def test_the_state_gate_answers_first_even_though_the_ceiling_is_also_broken(
        self, api
    ):
        """PRD §2.5: "When a single request could fail several checks, the server
        evaluates them in a fixed order and reports the first failure it finds. Text
        order elsewhere in this document is not authoritative; this ladder is."

        PRD §3.4: "The owning programme must be `ACTIVE`, otherwise
        `ERR_PROGRAM_NOT_ACTIVE`."

        The programme is only `PENDING_APPROVAL`, so the rung-7 state gate answers
        409 and the rung-20 coverage ceiling — equally broken by the same call —
        never gets to speak.

        Design: Difficulty/priority_pair_validation_conflict/program_state_gate_beats_coverage_ceiling_on_execute
        """
        ctx = self._submitted_program_carrying_an_oversized_swap(api)
        assert ctx["program"]["status"] == "PENDING_APPROVAL"

        error = validate_error(
            api.execute_hedge_instrument(ctx["instrument"]["id"], headers=TREASURY),
            ERR_PROGRAM_NOT_ACTIVE,
            409,
        )
        assert error["error_id"] != ERR_COVERAGE_LIMIT_EXCEEDED

    def test_activating_the_programme_lets_the_masked_ceiling_surface(self, api):
        """PRD §3.3: "The second is the coverage floor: the programme's
        `planned_coverage_pct_delta` must be greater than or equal to the governing
        policy's `min_coverage_pct`, otherwise `ERR_COVERAGE_FLOOR_NOT_MET`."

        PRD §3.4: "The post-trade delta-adjusted coverage must not exceed the
        governing policy's `max_coverage_pct`, and this comparison is deliberately
        made on the *unrounded* quotient — the delta-adjusted gallons the programme
        would hold after this trade, divided by `consumption_basis_gallons` and
        multiplied by 100, with no rounding applied before the comparison."

        Activation reads the floor and never the ceiling, so a programme planned at
        72.73 percent activates happily; the identical execute call then answers 422
        on the ceiling, which is what proves the condition was live and merely
        masked.

        Design: Difficulty/priority_pair_validation_conflict/program_state_gate_beats_coverage_ceiling_on_execute
        """
        ctx = self._submitted_program_carrying_an_oversized_swap(api)
        validate_error(
            api.execute_hedge_instrument(ctx["instrument"]["id"], headers=TREASURY),
            ERR_PROGRAM_NOT_ACTIVE,
            409,
        )

        active = fx.do_activate_program(api, ctx["program"]["id"])
        assert active["status"] == "ACTIVE"
        assert_pct(
            active["planned_coverage_pct_delta"], 72.73, "planned_coverage_pct_delta"
        )

        error = validate_error(
            api.execute_hedge_instrument(ctx["instrument"]["id"], headers=TREASURY),
            ERR_COVERAGE_LIMIT_EXCEEDED,
            422,
        )
        assert error["error_id"] != ERR_PROGRAM_NOT_ACTIVE

    def test_neither_refusal_moves_a_single_ledger(self, api):
        """PRD §3.4: "Four business gates precede it, in the ladder order of §2.5."

        PRD §3.4: "Execution then cascades. It writes the new
        `margin_requirement_usd`, adds that amount to the counterparty's
        `utilized_credit_usd` and recomputes the counterparty's `utilization_pct`
        and `credit_posture`; it adds the trade's `notional_gallons` to the
        programme's `hedged_gallons` and the trade's `delta_adjusted_gallons` to the
        programme's `delta_adjusted_gallons` and recomputes all three coverage
        percentages; and it increments the instrument's, the counterparty's and the
        programme's `version` by one each."

        Every ledger in this scenario moves only on the far side of those gates, so
        two refusals on two different rungs, and afterwards the trade is still
        `PROPOSED`, the programme's executed book is still empty and the dealer has
        drawn no credit.

        Design: Difficulty/priority_pair_validation_conflict/program_state_gate_beats_coverage_ceiling_on_execute
        """
        ctx = self._submitted_program_carrying_an_oversized_swap(api)
        instrument_id = ctx["instrument"]["id"]

        validate_error(
            api.execute_hedge_instrument(instrument_id, headers=TREASURY),
            ERR_PROGRAM_NOT_ACTIVE,
            409,
        )
        fx.do_activate_program(api, ctx["program"]["id"])
        validate_error(
            api.execute_hedge_instrument(instrument_id, headers=TREASURY),
            ERR_COVERAGE_LIMIT_EXCEEDED,
            422,
        )

        assert_instrument_status(
            fx.read_instrument(api, instrument_id), trade_status="PROPOSED"
        )
        assert_program_coverage(
            fx.read_program(api, ctx["program"]["id"]),
            consumption_basis_gallons=11000000,
            hedged_gallons=0,
            delta_adjusted_gallons=0.00,
            coverage_pct_notional=0.00,
            coverage_pct_delta=0.00,
        )
        assert_counterparty_credit(
            fx.read_counterparty(api, ctx["counterparty"]["id"]),
            utilized_credit_usd=0.00,
            utilization_pct=0.00,
        )


class TestWeightLimitBeatsMissingActiveContract:
    @staticmethod
    def _oversized_directive_whose_destination_contract_has_expired(api):
        """A 12,000-gallon directive proposed while both stations were priced,
        read back after the destination's only contract has run out."""
        fx.set_clock(api, PROPOSAL_CLOCK)
        ctx = {"policy": fx.do_create_policy(api, policy_code="FY27-PP2")}
        ctx["origin"] = fx.do_create_station(api)
        ctx["destination"] = fx.do_create_station(
            api,
            iata_code="DFW",
            name="Dallas Fort Worth",
            into_plane_fee_usd_per_gal=0.0800,
        )
        ctx["origin_contract"] = fx.do_create_contract(api, ctx["origin"]["id"])
        ctx["destination_contract"] = fx.do_create_contract(
            api,
            ctx["destination"]["id"],
            contract_ref="DFW-2027-A",
            index_price_usd_per_gal=2.9000,
            differential_usd_per_gal=0.1200,
            term_end_date="2027-02-28",
        )
        fx.do_adjust_inventory(api, ctx["origin"]["id"], 500000)
        ctx["leg"] = fx.do_create_leg(
            api,
            ctx["origin"]["id"],
            ctx["destination"]["id"],
            flight_number="UA400",
            departure_date="2027-03-20",
        )
        ctx["directive"] = fx.do_propose_directive(api, ctx["leg"]["id"], 12000)
        fx.set_clock(api, POST_EXPIRY_CLOCK)
        return ctx

    def test_the_weight_limit_answers_although_it_carries_the_higher_status_code(
        self, api
    ):
        """PRD §2.5: "The practical consequence of this ladder is that a
        weight-limit failure on directive approval is reported ahead of a
        supply-contract failure, which is reported ahead of an inventory failure,
        which is reported ahead of an economics failure — even though all four
        conditions are false in the same request."

        PRD §2.5: "Uplift must not exceed the leg's `uplift_cap_gallons`, otherwise
        `ERR_TANKERING_WEIGHT_LIMIT` (422). This guards directive approval and
        directive reconciliation."

        The 422 wins over the 409 that the expired destination contract would have
        produced, so ordering by HTTP severity is the wrong reading of the ladder.

        Design: Difficulty/priority_pair_validation_conflict/weight_limit_beats_missing_active_contract_on_directive_approve
        """
        ctx = self._oversized_directive_whose_destination_contract_has_expired(api)

        leg = fx.read_flight_leg(api, ctx["leg"]["id"])
        assert_gallon_tenths(leg["uplift_cap_gallons"], 10600.00, "uplift_cap_gallons")
        assert_whole_gallons(
            ctx["directive"]["requested_uplift_gallons"],
            12000,
            "requested_uplift_gallons",
        )

        error = validate_error(
            api.approve_tankering_directive(ctx["directive"]["id"], headers=OPS),
            ERR_TANKERING_WEIGHT_LIMIT,
            422,
        )
        assert error["error_id"] != ERR_NO_ACTIVE_SUPPLY_CONTRACT

    def test_a_legal_uplift_then_surfaces_the_expired_destination_contract(self, api):
        """PRD §3.8: "Pricing a directive requires that the origin station and the
        destination station each have **exactly one** supply contract whose
        clock-derived `status` is `ACTIVE` at that instant."

        PRD §3.2: "Before `term_start_date` the contract is `SCHEDULED`; from
        `term_start_date` through `term_end_date` inclusive it is `ACTIVE`; after
        `term_end_date` it is `EXPIRED`."

        Revision is guarded by the contract rule but not by the weight rule, and at
        3,000 gallons the envelope is clear anyway: what answers is the 409 the
        first call hid, because the destination's only contract ended on 2027-02-28
        and the clock now reads March.

        Design: Difficulty/priority_pair_validation_conflict/weight_limit_beats_missing_active_contract_on_directive_approve
        """
        ctx = self._oversized_directive_whose_destination_contract_has_expired(api)
        validate_error(
            api.approve_tankering_directive(ctx["directive"]["id"], headers=OPS),
            ERR_TANKERING_WEIGHT_LIMIT,
            422,
        )

        sent_back = fx.do_request_directive_revision(
            api, ctx["directive"]["id"], "Cap exceeded; trim to the envelope."
        )
        assert sent_back["status"] == "NEEDS_REVISION"

        error = validate_error(
            api.revise_tankering_directive(
                ctx["directive"]["id"], f.revise_directive_payload(3000), headers=ANALYST
            ),
            ERR_NO_ACTIVE_SUPPLY_CONTRACT,
            409,
        )
        assert error["error_id"] != ERR_TANKERING_WEIGHT_LIMIT

    def test_the_rejected_approval_pins_no_price_and_the_rejected_revision_counts(
        self, api
    ):
        """PRD §3.8: "Approval then pins prices: `pinned_origin_price_usd_per_gal`
        and `pinned_destination_price_usd_per_gal` are frozen from the two active
        contracts' all-in prices as of the approval instant, and
        `pinned_origin_contract_ref` records the `contract_ref` of the origin
        contract selected."

        PRD §3.8: "A `FuelAnalyst` may then revise it, which advances
        `NEEDS_REVISION → PROPOSED`, overwrites `requested_uplift_gallons` with the
        new request value, re-runs the planned-basis burn penalty and savings
        against the *live* contracts so a contract change between passes is picked
        up, increments `revision_count` by one and increments the directive's
        `version` by one."

        Neither refusal writes: no price is pinned by the failed approval, and the
        failed revision leaves 12,000 gallons on the row with `revision_count`
        still zero.

        Design: Difficulty/priority_pair_validation_conflict/weight_limit_beats_missing_active_contract_on_directive_approve
        """
        ctx = self._oversized_directive_whose_destination_contract_has_expired(api)
        directive_id = ctx["directive"]["id"]

        validate_error(
            api.approve_tankering_directive(directive_id, headers=OPS),
            ERR_TANKERING_WEIGHT_LIMIT,
            422,
        )
        after_approval = fx.read_directive(api, directive_id)
        assert after_approval["status"] == "PROPOSED"
        assert_nothing_pinned(after_approval)

        fx.do_request_directive_revision(
            api, directive_id, "Cap exceeded; trim to the envelope."
        )
        validate_error(
            api.revise_tankering_directive(
                directive_id, f.revise_directive_payload(3000), headers=ANALYST
            ),
            ERR_NO_ACTIVE_SUPPLY_CONTRACT,
            409,
        )

        after_revision = fx.read_directive(api, directive_id)
        assert after_revision["status"] == "NEEDS_REVISION"
        assert after_revision["revision_count"] == 0
        assert_whole_gallons(
            after_revision["requested_uplift_gallons"],
            12000,
            "requested_uplift_gallons",
        )


class TestTermOverlapBeatsDuplicateContractRef:
    @staticmethod
    def _station_with_one_contract_through_june(api):
        fx.set_clock(api, PROPOSAL_CLOCK)
        station = fx.do_create_station(api)
        contract = fx.do_create_contract(api, station["id"])
        return {"station": station, "contract": contract}

    @staticmethod
    def _reuse_the_ref(api, station_id, **term):
        payload = f.supply_contract_payload(
            contract_ref="ORD-2027-A",
            index_basis="PLATTS_NWE",
            index_price_usd_per_gal=2.5000,
            differential_usd_per_gal=0.0300,
            **term,
        )
        return api.create_supply_contract(station_id, payload, headers=ADMIN)

    def test_the_overlap_answers_and_not_the_duplicate_reference(self, api):
        """PRD §3.2: "First, because contract terms are closed intervals, two
        contracts at the same station may not share even a single day; any
        intersection is rejected with `ERR_CONTRACT_TERM_OVERLAP`."

        PRD §2.5: "When a single request could fail several checks, the server
        evaluates them in a fixed order and reports the first failure it finds."

        Both candidates carry 409, so only the `error_id` distinguishes them: a
        March-to-April term inside the existing January-to-June term is refused on
        the overlap, even though the request also reuses `ORD-2027-A`.

        Design: Difficulty/priority_pair_validation_conflict/contract_term_overlap_beats_duplicate_contract_ref
        """
        ctx = self._station_with_one_contract_through_june(api)
        assert ctx["contract"]["term_start_date"] == "2027-01-01"
        assert ctx["contract"]["term_end_date"] == "2027-06-30"

        error = validate_error(
            self._reuse_the_ref(api, ctx["station"]["id"], **OVERLAPPING_TERM),
            ERR_CONTRACT_TERM_OVERLAP,
            409,
        )
        assert error["error_id"] != ERR_DUPLICATE_CONTRACT_REF

    def test_a_clean_eight_day_gap_leaves_only_the_duplicate_reference(self, api):
        """PRD §3.2: "Two temporal rules keep a station's contract history clean,
        and a duplicated `contract_ref` at the same station is separately rejected
        with `ERR_DUPLICATE_CONTRACT_REF`."

        PRD §3.2: "the number of days from the earlier contract's `term_end_date` to
        the later contract's `term_start_date` must be at least seven, so a gap of
        exactly seven days is accepted while a gap of six days is rejected with
        `ERR_CONTRACT_BUFFER_VIOLATION`."

        From 2027-06-30 to 2027-07-08 is eight days, which clears both temporal
        rules; the same reused reference that was masked a moment ago is now the
        only thing wrong with the request.

        Design: Difficulty/priority_pair_validation_conflict/contract_term_overlap_beats_duplicate_contract_ref
        """
        ctx = self._station_with_one_contract_through_june(api)
        validate_error(
            self._reuse_the_ref(api, ctx["station"]["id"], **OVERLAPPING_TERM),
            ERR_CONTRACT_TERM_OVERLAP,
            409,
        )

        error = validate_error(
            self._reuse_the_ref(api, ctx["station"]["id"], **SEPARATED_TERM),
            ERR_DUPLICATE_CONTRACT_REF,
            409,
        )
        assert error["error_id"] != ERR_CONTRACT_TERM_OVERLAP
        assert error["error_id"] != ERR_CONTRACT_BUFFER_VIOLATION

    def test_the_station_still_holds_exactly_one_priced_contract(self, api):
        """PRD §3.2: "On creation the server computes `all_in_price_usd_per_gal` as
        the sum of `index_price_usd_per_gal`, `differential_usd_per_gal` and the
        station's `into_plane_fee_usd_per_gal`, rounded to four decimal places —
        this is the price every tankering calculation uses."

        Two refusals later the original 2.4700 contract is the station's only one
        and is still `ACTIVE` at a February clock, so neither rejected candidate
        left a row behind.

        Design: Difficulty/priority_pair_validation_conflict/contract_term_overlap_beats_duplicate_contract_ref
        """
        ctx = self._station_with_one_contract_through_june(api)
        validate_error(
            self._reuse_the_ref(api, ctx["station"]["id"], **OVERLAPPING_TERM),
            ERR_CONTRACT_TERM_OVERLAP,
            409,
        )
        validate_error(
            self._reuse_the_ref(api, ctx["station"]["id"], **SEPARATED_TERM),
            ERR_DUPLICATE_CONTRACT_REF,
            409,
        )

        rows, _ = validate_paginated(
            api.list_supply_contracts(ctx["station"]["id"], headers=ADMIN)
        )
        assert len(rows) == 1
        assert rows[0]["id"] == ctx["contract"]["id"]
        assert_price(
            rows[0]["all_in_price_usd_per_gal"], 2.4700, "all_in_price_usd_per_gal"
        )
        assert rows[0]["status"] == "ACTIVE"
