"""One request, three or four entities: cascades that reach rows nobody named.

A failing effectiveness test ends up incrementing a policy counter. Terminating
a trade ends up returning a dealer's cash — but only the cash that was actually
posted. Publishing a revaluation ends up breaching a credit posture without
raising a single error.
"""

from test_helpers import (
    assert_counterparty_credit,
    assert_effectiveness_outcome,
    assert_instrument_ledgers,
    assert_instrument_status,
    assert_money,
    assert_mtm_totals,
    assert_program_accounting,
    assert_program_coverage,
    assert_system_breach_exception,
    fixtures as fx,
)

DEALER_A = dict(
    counterparty_code="DLRA",
    legal_name="Dealer A Bank NA",
    credit_rating="A",
    credit_limit_usd=1000000.00,
)


def _posting_by_id(api, instrument_id, posting_id):
    """Collateral rows are readable only through their parents' lists."""
    rows = fx.list_instrument_postings(api, instrument_id)
    matches = [row for row in rows if row["id"] == posting_id]
    assert matches, f"posting {posting_id} not listed under instrument {instrument_id}"
    return matches[0]


class TestEffectivenessFailureReachesThePolicyCounter:
    @staticmethod
    def _designated_swap_carrying_a_two_hundred_thousand_dollar_mark(api):
        return fx.setup_designated_swap_with_published_mtm(
            api,
            policy_overrides=dict(policy_code="FY27-TC1"),
            counterparty_overrides=DEALER_A,
            program_overrides=dict(program_code="HP-TC1", target_coverage_pct=20.00),
            swap_overrides=dict(
                notional_gallons=2000000,
                strike_usd_per_gal=2.4000,
                maturity_month="2027-03",
            ),
            period_month="2027-02",
            settlement_index_usd_per_gal=2.5000,
        )

    def test_the_failure_moves_the_mark_between_the_programme_buckets(self, api):
        """PRD §3.6: "The second hop fires because the instrument left
        `DESIGNATED`: the programme's `designated_mtm_usd` and
        `undesignated_mtm_usd` are reclassified by moving the instrument's
        `mtm_value_usd` out of the designated bucket and into the undesignated
        one, after which the programme's `earnings_volatility_usd` is set to the
        absolute value of its `undesignated_mtm_usd` and its `compliance_posture`
        is recomputed".

        The 200,000.00 mark sat in the designated bucket with the programme
        `COMPLIANT`; one 0.3000 cumulative ratio moves it across, and 200,000.00
        of volatility against a 150,000.00 limit is a `BREACH`.

        Design: Difficulty/transitive_cascade/effectiveness_fail_dedesignation_reaches_policy_exception_count
        """
        ctx = self._designated_swap_carrying_a_two_hundred_thousand_dollar_mark(api)
        assert_program_accounting(
            ctx["program"],
            designated_mtm_usd=200000.00,
            undesignated_mtm_usd=0.00,
            earnings_volatility_usd=0.00,
            compliance_posture="COMPLIANT",
        )
        assert fx.read_policy(api, ctx["policy"]["id"])["open_exception_count"] == 0

        filed = fx.do_file_effectiveness_test(
            api, ctx["instrument"]["id"], "2027-02", -30000.00, 100000.00
        )
        assert_effectiveness_outcome(
            filed, period_ratio=0.3000, cumulative_ratio=0.3000, result="FAIL"
        )

        assert_instrument_status(
            fx.read_instrument(api, ctx["instrument"]["id"]),
            trade_status="EXECUTED",
            accounting_status="DEDESIGNATED",
        )
        assert_program_accounting(
            fx.read_program(api, ctx["program"]["id"]),
            designated_mtm_usd=0.00,
            undesignated_mtm_usd=200000.00,
            earnings_volatility_usd=200000.00,
            compliance_posture="BREACH",
        )

    def test_the_breach_raises_one_system_exception_and_counts_it_on_the_policy(
        self, api
    ):
        """PRD §3.6: "The third hop fires only because the posture became
        `BREACH`: a policy exception row is created with `origin` `SYSTEM_BREACH`,
        `reason_code` `EARNINGS_VOLATILITY_BREACH`, `status` `REQUESTED`,
        `hedge_program_id` set to this programme, `hedge_instrument_id` set to this
        instrument, `requested_by_user_id` null, and `justification` reading
        exactly `Auto-raised: undesignated mark-to-market exceeds policy earnings
        volatility limit.`"

        PRD §3.6: "The fourth hop fires only because that exception now exists in
        `REQUESTED`: the governing policy's `open_exception_count` is incremented
        by one."

        The request named an instrument and two dollar amounts; four hops later a
        policy row nobody mentioned has a different counter.

        Design: Difficulty/transitive_cascade/effectiveness_fail_dedesignation_reaches_policy_exception_count
        """
        ctx = self._designated_swap_carrying_a_two_hundred_thousand_dollar_mark(api)
        fx.do_file_effectiveness_test(
            api, ctx["instrument"]["id"], "2027-02", -30000.00, 100000.00
        )

        rows = fx.list_exceptions(api, hedge_instrument_id=ctx["instrument"]["id"])
        assert len(rows) == 1
        assert_system_breach_exception(
            rows[0],
            hedge_program_id=ctx["program"]["id"],
            hedge_instrument_id=ctx["instrument"]["id"],
        )

        assert fx.read_policy(api, ctx["policy"]["id"])["open_exception_count"] == 1

    def test_the_cascade_reclassifies_the_mark_without_revaluing_it(self, api):
        """PRD §3.6: "The first hop moves the accounting dimension `DESIGNATED →
        DEDESIGNATED`, leaving `trade_status` untouched."

        PRD §2.8: "Cascades in this system are strictly conditional and chained: a
        later hop fires only because an earlier hop actually changed something."

        The instrument's own `mtm_value_usd` is still the 200,000.00 the published
        run wrote: the cascade moved that figure between the programme's buckets
        and counted it on the policy, and no hop rewrote it.

        Design: Difficulty/transitive_cascade/effectiveness_fail_dedesignation_reaches_policy_exception_count
        """
        ctx = self._designated_swap_carrying_a_two_hundred_thousand_dollar_mark(api)
        fx.do_file_effectiveness_test(
            api, ctx["instrument"]["id"], "2027-02", -30000.00, 100000.00
        )

        instrument = fx.read_instrument(api, ctx["instrument"]["id"])
        assert_instrument_ledgers(instrument, mtm_value_usd=200000.00)
        assert_instrument_status(
            instrument, trade_status="EXECUTED", accounting_status="DEDESIGNATED"
        )


class TestTerminationReturnsCollateral:
    @staticmethod
    def _executed_trade_with_one_posted_and_one_required_row(api):
        ctx = fx.setup_active_program_with_executed_swap(
            api,
            policy_overrides=dict(policy_code="FY27-TC2"),
            counterparty_overrides=DEALER_A,
            program_overrides=dict(program_code="HP-TC2", target_coverage_pct=30.00),
            swap_overrides=dict(
                notional_gallons=3000000,
                strike_usd_per_gal=2.4000,
                maturity_month="2027-03",
            ),
        )
        counterparty_id = ctx["counterparty"]["id"]
        instrument_id = ctx["instrument"]["id"]

        first = fx.do_create_posting(api, counterparty_id, instrument_id)
        ctx["posted"] = fx.do_post_collateral(api, first["id"], 180000.00)
        ctx["required"] = fx.do_create_posting(api, counterparty_id, instrument_id)
        return ctx

    def test_only_the_posted_row_is_driven_to_returned(self, api):
        """PRD §3.4: "The second hop fires *because* the trade is now terminated:
        every collateral row against this trade that is in `POSTED` status advances
        `POSTED → RETURNED` with `returned_at` stamped from the logical clock,
        while rows still sitting in `REQUIRED` are deliberately left untouched."

        PRD §3.5: "crucially, `posted_amount_usd` is retained on the row for audit
        and is *not* zeroed."

        The two rows face the same trade and the same dealer; the discriminator is
        their own status, so the 180,000.00 that was actually posted comes back and
        the zero-dollar requirement stays outstanding.

        Design: Difficulty/transitive_cascade/terminate_returns_posted_collateral_and_restores_counterparty
        """
        ctx = self._executed_trade_with_one_posted_and_one_required_row(api)
        assert ctx["posted"]["status"] == "POSTED"
        assert ctx["required"]["status"] == "REQUIRED"
        assert_money(
            ctx["required"]["required_amount_usd"], 0.00, "required_amount_usd"
        )

        fx.do_terminate_instrument(
            api, ctx["instrument"]["id"], "Unwound after the counterparty review."
        )

        returned = _posting_by_id(
            api, ctx["instrument"]["id"], ctx["posted"]["id"]
        )
        assert returned["status"] == "RETURNED"
        assert returned["returned_at"] is not None
        assert_money(returned["posted_amount_usd"], 180000.00, "posted_amount_usd")

        untouched = _posting_by_id(
            api, ctx["instrument"]["id"], ctx["required"]["id"]
        )
        assert untouched["status"] == "REQUIRED"
        assert untouched["returned_at"] is None

    def test_the_dealer_ledgers_come_back_to_their_pre_execution_values(self, api):
        """PRD §3.4: "The third hop fires *because* those rows became returned: the
        counterparty's `posted_collateral_usd` is reduced by their
        `posted_amount_usd`, its `utilized_credit_usd` is reduced by the trade's
        pre-termination `margin_requirement_usd`, and its `utilization_pct` and
        `credit_posture` are recomputed."

        Both dollar ledgers land back at zero, and `open_margin_call_count` stays
        at one precisely because the surviving `REQUIRED` row was left alone.

        Design: Difficulty/transitive_cascade/terminate_returns_posted_collateral_and_restores_counterparty
        """
        ctx = self._executed_trade_with_one_posted_and_one_required_row(api)

        fx.do_terminate_instrument(
            api, ctx["instrument"]["id"], "Unwound after the counterparty review."
        )

        assert_counterparty_credit(
            fx.read_counterparty(api, ctx["counterparty"]["id"]),
            utilized_credit_usd=0.00,
            posted_collateral_usd=0.00,
            utilization_pct=0.00,
            credit_posture="NORMAL",
            open_margin_call_count=1,
        )

    def test_the_first_hop_empties_the_trade_and_the_programme_book(self, api):
        """PRD §3.4: "The first hop advances `trade_status` `EXECUTED →
        TERMINATED`, sets `margin_requirement_usd` to 0, moves `accounting_status`
        to `DEDESIGNATED` if and only if it was `DESIGNATED`, subtracts the trade's
        `notional_gallons` from the programme's `hedged_gallons` and its
        `delta_adjusted_gallons` from the programme's `delta_adjusted_gallons`,
        decrements `open_instrument_count` by one and recomputes all three coverage
        percentages."

        The chain is strictly ordered: the trade's own row is emptied first, and
        only that makes the collateral hop and then the dealer hop fire.

        Design: Difficulty/transitive_cascade/terminate_returns_posted_collateral_and_restores_counterparty
        """
        ctx = self._executed_trade_with_one_posted_and_one_required_row(api)

        terminated = fx.do_terminate_instrument(
            api, ctx["instrument"]["id"], "Unwound after the counterparty review."
        )
        assert_instrument_status(terminated, trade_status="TERMINATED")
        assert_instrument_ledgers(
            terminated, margin_requirement_usd=0, collateral_posted_usd=0.00
        )

        assert_program_coverage(
            fx.read_program(api, ctx["program"]["id"]),
            consumption_basis_gallons=11000000,
            hedged_gallons=0,
            delta_adjusted_gallons=0.00,
            coverage_pct_notional=0.00,
            coverage_pct_delta=0.00,
            open_instrument_count=0,
        )


class TestPublicationRaisesAMarginCall:
    @staticmethod
    def _collateralised_trade_and_a_computed_adverse_run(api):
        ctx = fx.setup_active_program_with_executed_swap(
            api,
            policy_overrides=dict(
                policy_code="FY27-TC3", max_earnings_volatility_usd=500000.00
            ),
            counterparty_overrides=dict(
                counterparty_code="DLRA",
                legal_name="Dealer A Bank NA",
                credit_rating="A",
                credit_limit_usd=500000.00,
            ),
            program_overrides=dict(program_code="HP-TC3", target_coverage_pct=20.00),
            swap_overrides=dict(
                notional_gallons=2000000,
                strike_usd_per_gal=2.5000,
                maturity_month="2027-03",
            ),
        )
        first = fx.do_create_posting(
            api, ctx["counterparty"]["id"], ctx["instrument"]["id"]
        )
        ctx["posted"] = fx.do_post_collateral(api, first["id"], 120000.00)

        ctx["run"] = fx.do_open_mtm_run(api, "2027-02", 2.3000)
        ctx["run"] = fx.do_compute_mtm_run(api, ctx["run"]["id"])
        return ctx

    def test_the_adverse_mark_raises_margin_and_creates_exactly_one_call(self, api):
        """PRD §3.7: "The first hop re-runs the margin calculation of §3.4 for
        every in-scope instrument against the newly published `mtm_value_usd` and
        overwrites each `margin_requirement_usd`; because a negative mark-to-market
        feeds the base margin at the 1.10 adverse factor, a bad month mechanically
        raises margin."

        PRD §3.7: "The second hop fires because those requirements moved: for every
        instrument whose `margin_requirement_usd` now exceeds its
        `collateral_posted_usd`, a collateral row is created with `origin`
        `MTM_MARGIN_CALL`, `status` `REQUIRED`, `collateral_type` `CASH` and
        `required_amount_usd` equal to the difference between the new
        `margin_requirement_usd` and the current `collateral_posted_usd`".

        A -400,000.00 mark adds 440,000.00 to the 120,000.00 base, and the gap
        over the 120,000.00 already posted is called in one row.

        Design: Difficulty/transitive_cascade/mtm_publish_adverse_margin_call_chain
        """
        ctx = self._collateralised_trade_and_a_computed_adverse_run(api)
        assert_mtm_totals(
            ctx["run"],
            status="COMPUTED",
            instrument_count=1,
            total_mtm_usd=-400000.00,
            designated_mtm_usd=0.00,
            undesignated_mtm_usd=-400000.00,
        )

        published = fx.do_publish_mtm_run(api, ctx["run"]["id"])
        assert_mtm_totals(published, status="PUBLISHED", margin_calls_created=1)

        assert_instrument_ledgers(
            fx.read_instrument(api, ctx["instrument"]["id"]),
            margin_requirement_usd=560000.00,
        )

        calls = fx.list_instrument_postings(
            api, ctx["instrument"]["id"], origin="MTM_MARGIN_CALL"
        )
        assert len(calls) == 1
        assert calls[0]["status"] == "REQUIRED"
        assert calls[0]["collateral_type"] == "CASH"
        assert_money(calls[0]["required_amount_usd"], 440000.00, "required_amount_usd")

    def test_the_dealer_posture_breaches_and_the_call_is_counted_as_open(self, api):
        """PRD §3.7: "The third hop fires because those rows now exist in
        `REQUIRED`: each affected counterparty has its `open_margin_call_count`
        incremented by one, its `utilized_credit_usd` set to the sum of
        `margin_requirement_usd` over its executed instruments, and its
        `utilization_pct` and `credit_posture` recomputed."

        PRD §3.1: "Exactly 90.00 is therefore `CONSTRAINED`, and exactly 100.00 is
        `BREACH`."

        Utilisation goes from 24.00 percent to 112.00 percent. Nothing is refused:
        the credit ceiling gates trade requests, while a publication simply records
        where the dealer now stands.

        Design: Difficulty/transitive_cascade/mtm_publish_adverse_margin_call_chain
        """
        ctx = self._collateralised_trade_and_a_computed_adverse_run(api)
        assert_counterparty_credit(
            fx.read_counterparty(api, ctx["counterparty"]["id"]),
            utilized_credit_usd=120000.00,
            posted_collateral_usd=120000.00,
            utilization_pct=24.00,
            credit_posture="NORMAL",
            open_margin_call_count=0,
        )

        fx.do_publish_mtm_run(api, ctx["run"]["id"])

        assert_counterparty_credit(
            fx.read_counterparty(api, ctx["counterparty"]["id"]),
            utilized_credit_usd=560000.00,
            utilization_pct=112.00,
            credit_posture="BREACH",
            open_margin_call_count=1,
        )

    def test_the_fourth_hop_stops_short_of_raising_an_exception(self, api):
        """PRD §3.7: "The fourth part reclassifies programmes: for every programme
        owning an in-scope instrument, `designated_mtm_usd` and
        `undesignated_mtm_usd` are set from that programme's buckets of this run,
        then `earnings_volatility_usd` and `compliance_posture` are recomputed; a
        programme whose posture becomes `BREACH` auto-raises a `SYSTEM_BREACH`
        policy exception".

        PRD §3.7: "Every in-scope instrument whose `maturity_month` is no later
        than the run's `period_month` advances `trade_status` `EXECUTED →
        SETTLED`, so a matured trade still records one final margin recomputation
        before it leaves the book."

        400,000.00 of undesignated volatility is inside the 500,000.00 limit, so
        the programme stays `COMPLIANT`, no exception is raised and the policy
        counter never moves — and the March trade does not settle in a February
        run.

        Design: Difficulty/transitive_cascade/mtm_publish_adverse_margin_call_chain
        """
        ctx = self._collateralised_trade_and_a_computed_adverse_run(api)

        published = fx.do_publish_mtm_run(api, ctx["run"]["id"])
        assert_mtm_totals(published, settled_instrument_count=0)

        assert_program_accounting(
            fx.read_program(api, ctx["program"]["id"]),
            designated_mtm_usd=0.00,
            undesignated_mtm_usd=-400000.00,
            earnings_volatility_usd=400000.00,
            compliance_posture="COMPLIANT",
        )
        assert fx.read_policy(api, ctx["policy"]["id"])["open_exception_count"] == 0
        assert fx.list_exceptions(api) == []

        assert_instrument_status(
            fx.read_instrument(api, ctx["instrument"]["id"]),
            trade_status="EXECUTED",
            accounting_status="UNDESIGNATED",
        )
