"""Lifecycle edges: what a state permits, what it refuses, and what it settles.

A rejected transition must be a true no-op — no stamp re-written, no counter
double-moved — and a transition on one status dimension must leave the other
dimension alone.
"""

import pytest
from test_helpers import (
    ACCOUNTANT,
    ADMIN,
    ANALYST,
    ANALYST_USER_ID,
    ERR_FORECAST_INVALID_STATE,
    ERR_INSTRUMENT_INVALID_TRADE_STATE,
    ERR_PROGRAM_INVALID_STATE,
    TREASURY,
    TRM_USER_ID,
    assert_counterparty_credit,
    assert_instrument_ledgers,
    assert_instrument_status,
    assert_money,
    assert_mtm_totals,
    assert_pct,
    assert_program_accounting,
    assert_program_coverage,
    factories as f,
    fixtures as fx,
    make_analyst_headers,
    make_treasury_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

CORNER_POLICY = dict(
    policy_code="FY27-CORNER",
    min_coverage_pct=5.00,
    max_single_counterparty_pct=100.00,
    max_earnings_volatility_usd=500000.00,
)
CORNER_COUNTERPARTY = dict(
    counterparty_code="DLRC",
    legal_name="Dealer C Bank NA",
    credit_rating="A",
    credit_limit_usd=2000000.00,
)
CORNER_PROGRAM = dict(
    program_code="HP-CORNER",
    period_start_month="2027-01",
    period_end_month="2027-03",
    route_groups=["DOMESTIC_SHORT"],
    target_coverage_pct=30.00,
)


class TestHedgeProgramInitialState:
    def test_a_new_programme_is_draft_with_every_ledger_at_zero(self, api):
        """PRD §3.3: "A hedge programme is created by a `FuelAnalyst` in `DRAFT`
        status, bound to a governing policy by `policy_id`".

        PRD §3.3: "At creation every computed ledger —
        `consumption_basis_gallons`, `hedged_gallons`, `delta_adjusted_gallons`,
        `coverage_pct_notional`, `coverage_pct_delta`,
        `planned_coverage_pct_delta`, `designated_mtm_usd`,
        `undesignated_mtm_usd`, `earnings_volatility_usd`,
        `open_instrument_count` and `return_count` — is zero,
        `compliance_posture` is `COMPLIANT`, and `submitted_by_user_id` is null."

        Design: Corner/state_machines/hedge_program_is_born_in_draft_with_zeroed_derived_fields
        """
        policy = fx.do_create_policy(api, **CORNER_POLICY)
        fx.do_create_published_forecast(api)

        data = validate_success(
            api.create_hedge_program(
                f.hedge_program_payload(policy["id"], **CORNER_PROGRAM), headers=ANALYST
            ),
            201,
        )

        assert data["status"] == "DRAFT"
        assert data["version"] == 1
        assert_program_coverage(
            data,
            consumption_basis_gallons=0,
            hedged_gallons=0,
            delta_adjusted_gallons=0,
            coverage_pct_notional=0.00,
            coverage_pct_delta=0.00,
            planned_coverage_pct_delta=0.00,
            open_instrument_count=0,
        )
        assert_program_accounting(
            data,
            designated_mtm_usd=0.00,
            undesignated_mtm_usd=0.00,
            earnings_volatility_usd=0.00,
            compliance_posture="COMPLIANT",
        )
        assert data["return_count"] == 0
        assert data["submitted_by_user_id"] is None

    def test_an_eligible_published_forecast_does_not_size_the_programme_at_creation(
        self, api
    ):
        """PRD §3.3: "**Sizing** is the analyst's act of freezing a demand basis
        onto the programme. It is valid as the transition `DRAFT → SIZING` and
        equally as a re-run `SIZING → SIZING`".

        The forecast created here satisfies every basis condition, so if creation
        sized anything the basis would be non-zero; it stays zero until the
        explicit transition runs.

        Design: Corner/state_machines/hedge_program_is_born_in_draft_with_zeroed_derived_fields
        """
        policy = fx.do_create_policy(api, **CORNER_POLICY)
        fx.do_create_published_forecast(api)
        program = fx.do_create_program(api, policy["id"], **CORNER_PROGRAM)

        assert_program_coverage(program, consumption_basis_gallons=0)

        sized = fx.do_size_program(api, program["id"])
        assert sized["status"] == "SIZING"
        assert_program_coverage(
            sized, consumption_basis_gallons=fx.SINGLE_FORECAST_BASIS_GALLONS
        )


class TestUndeclaredProgramTransitions:
    def test_neither_activate_nor_submit_is_reachable_from_draft(self, api):
        """PRD §2.5: "**State gates.** The target resource must be in a state
        from which the requested transition is declared".

        PRD §3.3: "**Submission** advances a programme `SIZING →
        PENDING_APPROVAL`" and "Activating it moves it `PENDING_APPROVAL →
        ACTIVE`", so a `DRAFT` programme declares neither edge.

        Design: Corner/state_machines/activate_and_submit_from_draft_both_return_409
        """
        policy = fx.do_create_policy(api, **CORNER_POLICY)
        program = fx.do_create_program(api, policy["id"], **CORNER_PROGRAM)

        validate_error(
            api.activate_hedge_program(
                program["id"], headers=make_treasury_headers(TRM_USER_ID)
            ),
            ERR_PROGRAM_INVALID_STATE,
            409,
        )
        validate_error(
            api.submit_hedge_program(
                program["id"], headers=make_analyst_headers(ANALYST_USER_ID)
            ),
            ERR_PROGRAM_INVALID_STATE,
            409,
        )

        after = fx.read_program(api, program["id"])
        assert after["status"] == "DRAFT"
        assert after["version"] == 1
        assert after["submitted_by_user_id"] is None
        assert after["return_count"] == 0

    def test_the_state_gate_outranks_the_activation_gates_it_precedes(self, api):
        """PRD §2.5 orders "**State gates.**" at step 7 ahead of both
        "**Segregation of duties,** otherwise `ERR_SEGREGATION_OF_DUTIES`
        (403)." at step 18 and "**Coverage floor** on programme activation,
        otherwise `ERR_COVERAGE_FLOOR_NOT_MET` (422)." at step 19.

        This programme has never been submitted and has no coverage at all, so
        both later gates are also false; only the state gate may be reported.

        Design: Corner/state_machines/activate_and_submit_from_draft_both_return_409
        """
        policy = fx.do_create_policy(api, **CORNER_POLICY)
        program = fx.do_create_program(api, policy["id"], **CORNER_PROGRAM)

        response = api.activate_hedge_program(
            program["id"], headers=make_treasury_headers(TRM_USER_ID)
        )
        validate_error(response, ERR_PROGRAM_INVALID_STATE, 409)


class TestForecastPublicationIsNotRepeatable:
    def test_republishing_is_refused_without_restamping_published_at(self, api):
        """PRD §3.3: "Publishing something already `PUBLISHED` is rejected with
        `ERR_FORECAST_INVALID_STATE`."

        PRD §3.3: "Publishing a forecast advances it `DRAFT → PUBLISHED`, stamps
        `published_at` with the logical clock instant and increments the
        forecast's `version` by one." A refused repeat therefore must leave both
        the stamp and the version exactly as the first publication left them.

        Design: Corner/state_machines/republishing_a_published_forecast_returns_409_and_keeps_published_at
        """
        forecast = fx.do_create_forecast(api)
        published = fx.do_publish_forecast(api, forecast["id"])

        validate_error(
            api.publish_consumption_forecast(forecast["id"], headers=ANALYST),
            ERR_FORECAST_INVALID_STATE,
            409,
        )

        rows, _meta = validate_paginated(
            api.list_consumption_forecasts(
                headers=ANALYST, params={"status": "PUBLISHED"}
            )
        )
        assert len(rows) == 1
        assert rows[0]["status"] == "PUBLISHED"
        assert rows[0]["published_at"] == published["published_at"]
        assert rows[0]["version"] == published["version"]


class TestTerminatedTradeIsLockedDown:
    @pytest.mark.parametrize("verb", ["execute", "terminate"])
    def test_a_terminated_proposal_refuses_further_trade_transitions(self, api, verb):
        """PRD §3.4: "The trade dimension runs `PROPOSED`, then either
        `EXECUTED` or `TERMINATED`, with `SETTLED` and `TERMINATED` as its
        terminal values."

        PRD §3.4: "Terminating a trade that is already `SETTLED` or `TERMINATED`
        yields `ERR_INSTRUMENT_INVALID_TRADE_STATE`."

        Design: Corner/state_machines/terminated_proposed_trade_rejects_execute_and_second_terminate
        """
        ctx = fx.setup_single_forecast_sized_program(
            api,
            policy_overrides=CORNER_POLICY,
            counterparty_overrides=CORNER_COUNTERPARTY,
            program_overrides=CORNER_PROGRAM,
        )
        instrument = fx.do_propose_swap(
            api,
            ctx["program"]["id"],
            ctx["counterparty"]["id"],
            notional_gallons=1000000,
            strike_usd_per_gal=2.5000,
            maturity_month="2027-03",
        )
        fx.do_terminate_instrument(
            api, instrument["id"], "Trade cancelled before execution by the desk."
        )

        if verb == "execute":
            response = api.execute_hedge_instrument(
                instrument["id"], headers=make_treasury_headers(TRM_USER_ID)
            )
        else:
            response = api.terminate_hedge_instrument(
                instrument["id"],
                f.terminate_payload("Second attempt at the same cancellation."),
                headers=make_treasury_headers(TRM_USER_ID),
            )
        validate_error(response, ERR_INSTRUMENT_INVALID_TRADE_STATE, 409)

    def test_the_refused_calls_do_not_decrement_the_open_count_a_second_time(self, api):
        """PRD §3.4: "Terminating a merely `PROPOSED` trade advances
        `trade_status` `PROPOSED → TERMINATED`, decrements the programme's
        `open_instrument_count` by one, recomputes `planned_coverage_pct_delta`,
        and increments the instrument's and the programme's `version` by one
        each; nothing financial has happened yet, so nothing financial is
        reversed."

        Because nothing financial ever happened, PRD §3.4's execution ledgers
        must also still be untouched on the dealer.

        Design: Corner/state_machines/terminated_proposed_trade_rejects_execute_and_second_terminate
        """
        ctx = fx.setup_single_forecast_sized_program(
            api,
            policy_overrides=CORNER_POLICY,
            counterparty_overrides=CORNER_COUNTERPARTY,
            program_overrides=CORNER_PROGRAM,
        )
        instrument = fx.do_propose_swap(
            api,
            ctx["program"]["id"],
            ctx["counterparty"]["id"],
            notional_gallons=1000000,
            strike_usd_per_gal=2.5000,
            maturity_month="2027-03",
        )
        fx.do_terminate_instrument(
            api, instrument["id"], "Trade cancelled before execution by the desk."
        )

        validate_error(
            api.execute_hedge_instrument(
                instrument["id"], headers=make_treasury_headers(TRM_USER_ID)
            ),
            ERR_INSTRUMENT_INVALID_TRADE_STATE,
            409,
        )
        validate_error(
            api.terminate_hedge_instrument(
                instrument["id"],
                f.terminate_payload("Second attempt at the same cancellation."),
                headers=make_treasury_headers(TRM_USER_ID),
            ),
            ERR_INSTRUMENT_INVALID_TRADE_STATE,
            409,
        )

        program = fx.read_program(api, ctx["program"]["id"])
        assert program["status"] == "SIZING"
        assert_program_coverage(
            program,
            hedged_gallons=0,
            planned_coverage_pct_delta=0.00,
            open_instrument_count=0,
        )

        counterparty = fx.read_counterparty(api, ctx["counterparty"]["id"])
        assert_counterparty_credit(
            counterparty,
            utilized_credit_usd=0.00,
            utilization_pct=0.00,
            credit_posture="NORMAL",
        )


class TestSettlementOnPublication:
    @staticmethod
    def _publish_over_a_matured_designated_swap(api):
        ctx = fx.setup_active_program_with_executed_swap(
            api,
            single_forecast=True,
            policy_overrides=CORNER_POLICY,
            counterparty_overrides=CORNER_COUNTERPARTY,
            program_overrides=CORNER_PROGRAM,
            swap_overrides=dict(
                notional_gallons=1000000,
                strike_usd_per_gal=2.5000,
                maturity_month="2027-02",
            ),
        )
        fx.do_designate_instrument(api, ctx["instrument"]["id"])
        run = fx.do_open_mtm_run(api, "2027-02", 2.7500)
        fx.do_compute_mtm_run(api, run["id"])
        ctx["run"] = validate_success(api.publish_mtm_run(run["id"], headers=ADMIN))
        return ctx

    def test_publication_raises_margin_then_settles_the_matured_trade(self, api):
        """PRD §3.7: "Only after those four parts have run does settlement occur.
        Every in-scope instrument whose `maturity_month` is no later than the
        run's `period_month` advances `trade_status` `EXECUTED → SETTLED`, so a
        matured trade still records one final margin recomputation before it
        leaves the book." Settlement "releases margin by setting
        `margin_requirement_usd` to 0" and "increments the run's
        `settled_instrument_count` by one".

        PRD §3.4: "A designation never touches `trade_status`, and an execution
        never touches `accounting_status`."

        Design: Corner/state_machines/mtm_publish_settles_matured_trade_without_disturbing_designation
        """
        ctx = self._publish_over_a_matured_designated_swap(api)

        assert_mtm_totals(
            ctx["run"],
            status="PUBLISHED",
            instrument_count=1,
            total_mtm_usd=250000.00,
            designated_mtm_usd=250000.00,
            undesignated_mtm_usd=0.00,
            margin_calls_created=1,
            settled_instrument_count=1,
        )

        instrument = fx.read_instrument(api, ctx["instrument"]["id"])
        assert_instrument_status(
            instrument, trade_status="SETTLED", accounting_status="DESIGNATED"
        )
        assert_instrument_ledgers(
            instrument, mtm_value_usd=250000.00, margin_requirement_usd=0.00
        )

    def test_settlement_releases_credit_but_leaves_the_margin_call_on_the_books(
        self, api
    ):
        """PRD §3.7: settlement "reducing the counterparty's
        `utilized_credit_usd` by the pre-settlement requirement, then recomputes
        the counterparty's `utilization_pct` and `credit_posture`".

        PRD §3.7: the third hop gives "each affected counterparty has its
        `open_margin_call_count` incremented by one", and settlement never
        reverses that count.

        PRD §3.7: "The fourth part reclassifies programmes: for every programme
        owning an in-scope instrument, `designated_mtm_usd` and `undesignated_mtm_usd`
        are set from that programme's buckets of this run, then
        `earnings_volatility_usd` and `compliance_posture` are recomputed".

        Design: Corner/state_machines/mtm_publish_settles_matured_trade_without_disturbing_designation
        """
        ctx = self._publish_over_a_matured_designated_swap(api)

        counterparty = fx.read_counterparty(api, ctx["counterparty"]["id"])
        assert_counterparty_credit(
            counterparty,
            utilized_credit_usd=0.00,
            utilization_pct=0.00,
            credit_posture="NORMAL",
            open_margin_call_count=1,
            posted_collateral_usd=0.00,
        )

        program = fx.read_program(api, ctx["program"]["id"])
        assert_program_coverage(
            program,
            hedged_gallons=0,
            delta_adjusted_gallons=0,
            coverage_pct_notional=0.00,
            coverage_pct_delta=0.00,
            open_instrument_count=0,
        )
        assert_program_accounting(
            program,
            designated_mtm_usd=250000.00,
            undesignated_mtm_usd=0.00,
            earnings_volatility_usd=0.00,
            compliance_posture="COMPLIANT",
        )
