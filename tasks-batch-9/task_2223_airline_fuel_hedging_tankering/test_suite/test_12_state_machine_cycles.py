"""State machines that loop, and one terminal state nobody can ask for.

An instrument's accounting dimension re-enters `DESIGNATED` through a stronger
guard than it first cleared. A directive re-enters `PROPOSED` through
`NEEDS_REVISION` as often as the controller likes, and reaches `SUPERSEDED` only
because a sibling was created. A programme visits `SIZING` again both by
re-running it and by being sent back from `PENDING_APPROVAL`.
"""

from test_helpers import (
    ACCOUNTANT,
    ANALYST_USER_ID,
    ANALYST_USER_ID_ALT,
    ERR_DIRECTIVE_INVALID_STATE,
    ERR_EXCEPTION_REQUIRED,
    OPS,
    assert_effectiveness_outcome,
    assert_instrument_status,
    assert_pct,
    assert_program_accounting,
    assert_program_coverage,
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

#: The 2,000,000-gallon swap that all three programmes in this file carry.
NL_SWAP = dict(
    notional_gallons=2000000,
    strike_usd_per_gal=2.4000,
    maturity_month="2027-03",
)


class TestRedesignationCycle:
    @staticmethod
    def _dedesignated_trade_and_its_auto_raised_exception(api):
        """A designated swap carrying a 200,000.00 mark, driven back to
        `DEDESIGNATED` by one failing effectiveness test."""
        ctx = fx.setup_designated_swap_with_published_mtm(
            api,
            policy_overrides=dict(policy_code="FY27-NL1"),
            counterparty_overrides=DEALER_A,
            program_overrides=dict(program_code="HP-NL1", target_coverage_pct=20.00),
            swap_overrides=NL_SWAP,
            period_month="2027-02",
            settlement_index_usd_per_gal=2.5000,
        )
        ctx["failed_test"] = fx.do_file_effectiveness_test(
            api, ctx["instrument"]["id"], "2027-02", -30000.00, 100000.00
        )
        ctx["exception"] = fx.find_auto_raised_exception(api, ctx["instrument"]["id"])
        return ctx

    def test_the_second_entry_needs_an_exception_the_first_entry_did_not(self, api):
        """PRD §3.6: "The second, `DEDESIGNATED → DESIGNATED`, is a
        re-designation and carries the same two gates plus a third: an `APPROVED`
        policy exception with `reason_code` `EARNINGS_VOLATILITY_BREACH` must
        already reference this instrument, otherwise `ERR_EXCEPTION_REQUIRED`."

        The auto-raised exception exists, but it is still `REQUESTED`, and the
        gate reads `APPROVED`: the trade stays `DEDESIGNATED` while its trade
        dimension is untouched.

        Design: Difficulty/non_linear_state_machine/instrument_accounting_dimension_redesignation_cycle
        """
        ctx = self._dedesignated_trade_and_its_auto_raised_exception(api)

        assert_effectiveness_outcome(
            ctx["failed_test"], period_ratio=0.3000, cumulative_ratio=0.3000, result="FAIL"
        )
        assert ctx["exception"]["status"] == "REQUESTED"
        assert ctx["exception"]["origin"] == "SYSTEM_BREACH"
        assert ctx["exception"]["requested_by_user_id"] is None

        validate_error(
            api.designate_hedge_instrument(ctx["instrument"]["id"], headers=ACCOUNTANT),
            ERR_EXCEPTION_REQUIRED,
            422,
        )

        assert_instrument_status(
            fx.read_instrument(api, ctx["instrument"]["id"]),
            trade_status="EXECUTED",
            accounting_status="DEDESIGNATED",
        )

    def test_the_approved_exception_lets_the_accounting_dimension_re_enter_designated(
        self, api
    ):
        """PRD §3.6: "Re-designation additionally reclassifies the instrument's
        `mtm_value_usd` out of the programme's `undesignated_mtm_usd` and back
        into its `designated_mtm_usd`, then recomputes the programme's
        `earnings_volatility_usd` and `compliance_posture` and increments the
        programme's `version` by one."

        PRD §3.9: "both decrement by one the `open_exception_count` of the policy
        governing the exception's `hedge_program_id` when that reference is not
        null (incrementing that policy's `version` by one)".

        The same call that was refused now succeeds, the 200,000.00 mark returns
        to the designated bucket, the programme is `COMPLIANT` again and the
        policy is back to no open exceptions.

        Design: Difficulty/non_linear_state_machine/instrument_accounting_dimension_redesignation_cycle
        """
        ctx = self._dedesignated_trade_and_its_auto_raised_exception(api)
        validate_error(
            api.designate_hedge_instrument(ctx["instrument"]["id"], headers=ACCOUNTANT),
            ERR_EXCEPTION_REQUIRED,
            422,
        )

        approved = fx.do_approve_exception(api, ctx["exception"]["id"])
        assert approved["status"] == "APPROVED"

        redesignated = fx.do_designate_instrument(api, ctx["instrument"]["id"])
        assert_instrument_status(
            redesignated, trade_status="EXECUTED", accounting_status="DESIGNATED"
        )

        assert_program_accounting(
            fx.read_program(api, ctx["program"]["id"]),
            designated_mtm_usd=200000.00,
            undesignated_mtm_usd=0.00,
            earnings_volatility_usd=0.00,
            compliance_posture="COMPLIANT",
        )
        assert fx.read_policy(api, ctx["policy"]["id"])["open_exception_count"] == 0

    def test_the_trade_dimension_holds_still_while_the_accounting_one_cycles(self, api):
        """PRD §3.4: "The two status dimensions of an instrument advance
        independently of each other. The trade dimension runs `PROPOSED`, then
        either `EXECUTED` or `TERMINATED`, with `SETTLED` and `TERMINATED` as its
        terminal values. The accounting dimension runs `UNDESIGNATED`,
        `DESIGNATED` and `DEDESIGNATED` and can cycle between the latter two
        without bound."

        PRD §3.6: "The `DESIGNATED → DEDESIGNATED → DESIGNATED` cycle may repeat
        without bound."

        Four observations of the accounting dimension — designated, de-designated
        by the failure, still de-designated after the refusal, designated again —
        and the trade dimension reads `EXECUTED` at every one of them.

        Design: Difficulty/non_linear_state_machine/instrument_accounting_dimension_redesignation_cycle
        """
        ctx = self._dedesignated_trade_and_its_auto_raised_exception(api)
        instrument_id = ctx["instrument"]["id"]

        after_failure = fx.read_instrument(api, instrument_id)
        assert_instrument_status(
            after_failure, trade_status="EXECUTED", accounting_status="DEDESIGNATED"
        )

        validate_error(
            api.designate_hedge_instrument(instrument_id, headers=ACCOUNTANT),
            ERR_EXCEPTION_REQUIRED,
            422,
        )
        after_refusal = fx.read_instrument(api, instrument_id)
        assert_instrument_status(
            after_refusal, trade_status="EXECUTED", accounting_status="DEDESIGNATED"
        )

        fx.do_approve_exception(api, ctx["exception"]["id"])
        after_cycle = fx.do_designate_instrument(api, instrument_id)
        assert_instrument_status(
            after_cycle, trade_status="EXECUTED", accounting_status="DESIGNATED"
        )
        assert after_cycle["designated_at"] is not None


class TestDirectiveRevisionCycleAndSupersession:
    @staticmethod
    def _directive_revised_twice(api):
        ctx = fx.setup_proposed_directive(
            api,
            3000,
            policy_overrides=dict(policy_code="FY27-NL2"),
            leg_overrides=dict(flight_number="UA300", departure_date="2027-02-17"),
        )
        directive_id = ctx["directive"]["id"]
        fx.do_request_directive_revision(
            api, directive_id, "First pass: payload too high."
        )
        fx.do_revise_directive(api, directive_id, 2000)
        fx.do_request_directive_revision(
            api, directive_id, "Second pass: still trim it."
        )
        ctx["directive"] = fx.do_revise_directive(api, directive_id, 1000)
        return ctx

    def test_proposed_is_re_entered_twice_and_both_passes_are_counted(self, api):
        """PRD §3.8: "Requesting a revision advances `PROPOSED → NEEDS_REVISION`
        with a `revision_note` and increments the directive's `version`."

        PRD §3.8: "The `PROPOSED → NEEDS_REVISION → PROPOSED` cycle may repeat
        without bound."

        Two round trips leave the directive back in the state it started in, with
        `revision_count` at 2 and the latest 1,000-gallon request on the row.

        Design: Difficulty/non_linear_state_machine/directive_revision_cycle_then_supersession
        """
        ctx = self._directive_revised_twice(api)

        assert ctx["directive"]["status"] == "PROPOSED"
        assert ctx["directive"]["revision_count"] == 2
        assert_whole_gallons(
            ctx["directive"]["requested_uplift_gallons"],
            1000,
            "requested_uplift_gallons",
        )

    def test_a_sibling_directive_supersedes_the_live_one_as_a_side_effect(self, api):
        """PRD §3.8: "As a system side effect, any earlier directive on the same
        leg whose `status` is `PROPOSED` or `NEEDS_REVISION` is displaced —
        `PROPOSED → SUPERSEDED` and `NEEDS_REVISION → SUPERSEDED` respectively —
        and has its `version` incremented by one; the new directive is the only
        live one."

        Nobody asked for the displacement and no endpoint performs it: creating a
        second directive on the same leg is the whole cause, and the new row
        starts its own revision count at zero.

        Design: Difficulty/non_linear_state_machine/directive_revision_cycle_then_supersession
        """
        ctx = self._directive_revised_twice(api)
        first_id = ctx["directive"]["id"]

        second = fx.do_propose_directive(api, ctx["leg"]["id"], 800)

        assert second["status"] == "PROPOSED"
        assert second["revision_count"] == 0
        assert_whole_gallons(
            second["requested_uplift_gallons"], 800, "requested_uplift_gallons"
        )

        displaced = fx.read_directive(api, first_id)
        assert displaced["status"] == "SUPERSEDED"
        assert displaced["revision_count"] == 2

    def test_a_superseded_directive_can_no_longer_be_disposed_of(self, api):
        """PRD §2.5: "**State gates.** The target resource must be in a state from
        which the requested transition is declared, and any cross-entity state
        gate must hold".

        `SUPERSEDED` is terminal and unreachable by request, so the approval that
        would have been legal one call earlier is now a state-gate failure, and
        the sibling that displaced it is unaffected.

        Design: Difficulty/non_linear_state_machine/directive_revision_cycle_then_supersession
        """
        ctx = self._directive_revised_twice(api)
        first_id = ctx["directive"]["id"]
        second = fx.do_propose_directive(api, ctx["leg"]["id"], 800)

        validate_error(
            api.approve_tankering_directive(first_id, headers=OPS),
            ERR_DIRECTIVE_INVALID_STATE,
            409,
        )

        assert fx.read_directive(api, first_id)["status"] == "SUPERSEDED"
        assert fx.read_directive(api, second["id"])["status"] == "PROPOSED"


class TestProgramReturnCycleAndResizeSelfLoop:
    @staticmethod
    def _sized_program_with_a_draft_regional_forecast(api):
        """A programme sized to 11,000,000 gallons with one proposed swap, plus a
        1,000,000-gallon `REGIONAL` forecast still in `DRAFT`."""
        ctx = fx.setup_sized_program(
            api,
            policy_overrides=dict(policy_code="FY27-NL3"),
            counterparty_overrides=DEALER_A,
            program_overrides=dict(program_code="HP-NL3", target_coverage_pct=20.00),
        )
        ctx["draft_forecast"] = fx.do_create_forecast(
            api,
            fleet_type="REGIONAL",
            route_group="DOMESTIC_SHORT",
            season="SUMMER",
            period_start_month="2027-01",
            period_end_month="2027-04",
            forecast_gallons=1000000,
        )
        ctx["instrument"] = fx.do_propose_swap(
            api, ctx["program"]["id"], ctx["counterparty"]["id"], **NL_SWAP
        )
        return ctx

    def test_the_first_sizing_run_freezes_the_two_published_forecasts_only(self, api):
        """PRD §3.3: "A forecast enters the basis only if all four of the
        following hold: its `status` is `PUBLISHED`; its `fleet_type` is one of the
        governing policy's `eligible_fleet_types`; its `route_group` is one of the
        programme's `route_groups`; and its month window sits wholly inside the
        programme's."

        The regional forecast is eligible on fleet and route group but is still a
        draft, so the basis is the 4,000,000 and 6,000,000 summer forecasts
        weighted at 1.10, and the proposed swap reads 18.18 percent against it.

        Design: Difficulty/non_linear_state_machine/program_return_cycle_with_resize_self_loop
        """
        ctx = self._sized_program_with_a_draft_regional_forecast(api)

        program = fx.read_program(api, ctx["program"]["id"])
        assert program["status"] == "SIZING"
        assert ctx["draft_forecast"]["status"] == "DRAFT"
        assert_program_coverage(
            program,
            consumption_basis_gallons=11000000,
            planned_coverage_pct_delta=18.18,
            open_instrument_count=1,
        )

    def test_the_return_edge_sends_it_back_to_sizing_and_clears_the_submitter(
        self, api
    ):
        """PRD §3.3: "Returning the programme moves it `PENDING_APPROVAL →
        SIZING`, accompanies the move with a `return_note`, increments
        `return_count` by one, clears `submitted_by_user_id` back to null and
        increments the programme's `version`; this revision loop may repeat
        without bound."

        `SIZING` is not only where the programme started: it is where the return
        edge points, which is what makes the graph a cycle rather than a chain.

        Design: Difficulty/non_linear_state_machine/program_return_cycle_with_resize_self_loop
        """
        ctx = self._sized_program_with_a_draft_regional_forecast(api)
        program_id = ctx["program"]["id"]

        submitted = fx.do_submit_program(api, program_id, ANALYST_USER_ID)
        assert submitted["status"] == "PENDING_APPROVAL"
        assert submitted["submitted_by_user_id"] == ANALYST_USER_ID

        returned = fx.do_return_program(
            api,
            program_id,
            return_note="Basis excludes the regional fleet; re-size.",
        )
        assert returned["status"] == "SIZING"
        assert returned["submitted_by_user_id"] is None
        assert returned["return_count"] == 1

    def test_the_re_size_self_loop_moves_the_basis_without_touching_the_swap(self, api):
        """PRD §3.3: "It is valid as the transition `DRAFT → SIZING` and equally
        as a re-run `SIZING → SIZING`" and "Re-sizing is the only route by which a
        forecast published after an earlier sizing run enters an already-sized
        programme."

        Publishing the regional forecast and re-sizing lifts the basis from
        11,000,000 to 12,100,000 gallons, which drops the planned coverage from
        18.18 to 16.53 percent although not one instrument changed: the swap is
        still the same `PROPOSED` 2,000,000 gallons.

        Design: Difficulty/non_linear_state_machine/program_return_cycle_with_resize_self_loop
        """
        ctx = self._sized_program_with_a_draft_regional_forecast(api)
        program_id = ctx["program"]["id"]
        fx.do_submit_program(api, program_id, ANALYST_USER_ID)
        fx.do_return_program(
            api, program_id, return_note="Basis excludes the regional fleet; re-size."
        )

        fx.do_publish_forecast(api, ctx["draft_forecast"]["id"])
        resized = fx.do_size_program(api, program_id)

        assert resized["status"] == "SIZING"
        assert_program_coverage(
            resized,
            consumption_basis_gallons=12100000,
            planned_coverage_pct_delta=16.53,
            hedged_gallons=0,
            open_instrument_count=1,
        )
        assert_instrument_status(
            fx.read_instrument(api, ctx["instrument"]["id"]), trade_status="PROPOSED"
        )

    def test_three_submissions_and_two_returns_still_reach_active(self, api):
        """PRD §3.3: "**Submission** advances a programme `SIZING →
        PENDING_APPROVAL` and requires that at least one instrument still be open
        on it — that is, `open_instrument_count` must be one or more."

        PRD §3.3: "The first is segregation of duties: the activating `X-User-ID`
        must differ from the `submitted_by_user_id` recorded at submission,
        otherwise `ERR_SEGREGATION_OF_DUTIES`."

        The programme visits `SIZING` three times and `PENDING_APPROVAL` three
        times, and the identity that finally counts is the last submitter,
        `u_analyst_2`, because each return cleared the field.

        Design: Difficulty/non_linear_state_machine/program_return_cycle_with_resize_self_loop
        """
        ctx = self._sized_program_with_a_draft_regional_forecast(api)
        program_id = ctx["program"]["id"]

        fx.do_submit_program(api, program_id, ANALYST_USER_ID)
        fx.do_return_program(
            api, program_id, return_note="Basis excludes the regional fleet; re-size."
        )
        fx.do_publish_forecast(api, ctx["draft_forecast"]["id"])
        fx.do_size_program(api, program_id)

        fx.do_submit_program(api, program_id, ANALYST_USER_ID_ALT)
        fx.do_return_program(
            api, program_id, return_note="One more look at counterparty spread."
        )
        fx.do_submit_program(api, program_id, ANALYST_USER_ID_ALT)

        active = fx.do_activate_program(api, program_id)
        assert active["status"] == "ACTIVE"
        assert active["return_count"] == 2
        assert active["submitted_by_user_id"] == ANALYST_USER_ID_ALT
        assert_pct(
            active["planned_coverage_pct_delta"], 16.53, "planned_coverage_pct_delta"
        )
