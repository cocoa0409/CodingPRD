"""Deposit schedules, payments, late penalties, and filing settlement
(PRD §3.6, §3.7)."""
from test_helpers import (
    ApiErrorId,
    create_rated_event,
    file_return,
    list_period_deposits,
    new_admin_headers,
    new_analyst_headers,
    new_reviewer_headers,
    setup_active_registration,
    setup_filed_return,
    setup_return_with_rated_event,
    validate_error,
    validate_success,
)


class TestDepositScheduleVariants:
    def _setup_two_methods(self):
        ca = setup_active_registration(
            deposit_method="SAFE_HARBOR",
            jurisdiction_overrides={"code": "CA-BOE", "name": "California"})
        nv = setup_active_registration(
            deposit_method="ACTUAL",
            jurisdiction_overrides={"code": "NV-TX", "name": "Nevada"})
        return ca, nv

    def test_safe_harbor_schedule_floor_blind_to_current_activity(self, api):
        """PRD §3.7: "When no such prior filed return exists, the schedule
        falls back to a floor of 10,000 cents (one hundred dollars) per
        deposit. Identical activity in the current period does not move a
        safe-harbor schedule."

        Design: Difficulty/dual_variant_calc/deposit_schedule_safe_harbor_vs_actual
        """
        ca, _nv = self._setup_two_methods()
        create_rated_event(ca["registration"], ca["jurisdiction"],
                           ca["product_class"], quantity_units=1000)
        deps = list_period_deposits(ca["registration"]["id"], "2026-08")
        assert deps[0]["window"] == "A"
        assert deps[0]["scheduled_amount_cents"] == 10000, (
            "SAFE_HARBOR floor with no prior filed return, unmoved by "
            "current-period activity")

    def test_actual_schedule_accumulates_window_events_at_close(self, api):
        """PRD §3.7: "Under the `ACTUAL` variant, the scheduled amount starts
        at zero and accumulates the period's own activity: the clock sweep at
        each window close sets the scheduled amount to the sum of `tax_cents`
        over the registration's events in that jurisdiction whose `event_date`
        falls inside the window".

        Design: Difficulty/dual_variant_calc/deposit_schedule_safe_harbor_vs_actual
        """
        _ca, nv = self._setup_two_methods()
        create_rated_event(nv["registration"], nv["jurisdiction"],
                           nv["product_class"], quantity_units=1000)
        deps_before = list_period_deposits(nv["registration"]["id"], "2026-08")
        assert deps_before[0]["scheduled_amount_cents"] == 0, (
            "ACTUAL schedule starts at zero before the window closes")

        validate_success(
            api.set_clock("2026-08-16T00:00:00Z", new_admin_headers()))
        deps_after = list_period_deposits(nv["registration"]["id"], "2026-08")
        assert deps_after[0]["scheduled_amount_cents"] == 24300, (
            "window A close sums the window's rated events")


class TestLateDepositPenaltyTiers:
    def _setup_two_periods(self):
        """One registration; 2026-08 and 2026-09 returns each with a rated
        1000-unit event; returns depA08, depB08, depA09 (each scheduled
        10000 under the SAFE_HARBOR floor)."""
        ctx = setup_active_registration()
        create_rated_event(ctx["registration"], ctx["jurisdiction"],
                           ctx["product_class"], quantity_units=1000)
        create_rated_event(ctx["registration"], ctx["jurisdiction"],
                           ctx["product_class"],
                           event_date="2026-09-05T00:00:00Z",
                           quantity_units=1000)
        deps08 = list_period_deposits(ctx["registration"]["id"], "2026-08")
        deps09 = list_period_deposits(ctx["registration"]["id"], "2026-09")
        return ctx, deps08[0], deps08[1], deps09[0]

    def test_late_penalty_tier_boundaries_5_and_6_days(self, api):
        """PRD §3.7: "Paid one to five days late — five days exactly still
        falls inside this tier — the penalty is two percent of the scheduled
        amount, rounded half-up to a whole cent. Paid six to fifteen days
        late, the penalty is five percent, rounded half-up."

        Design: Difficulty/combinatorial_formula/late_deposit_penalty_tiered_nonlinear
        """
        _ctx, dep_a08, dep_b08, _dep_a09 = self._setup_two_periods()
        admin = new_admin_headers()
        validate_success(api.set_clock("2026-08-30T00:00:00Z", admin))
        paid_a = validate_success(
            api.pay_deposit(dep_a08["id"], 10000, new_analyst_headers()))
        assert paid_a["penalty_cents"] == 200, (
            "due 2026-08-25 paid 2026-08-30 = 5 days late: 2% of 10000")

        validate_success(api.set_clock("2026-09-16T00:00:00Z", admin))
        paid_b = validate_success(
            api.pay_deposit(dep_b08["id"], 10000, new_analyst_headers()))
        assert paid_b["penalty_cents"] == 500, (
            "due 2026-09-10 paid 2026-09-16 = 6 days late: 5% of 10000")

    def test_late_penalty_tier3_with_daily_interest(self, api):
        """PRD §3.7: "Paid sixteen or more days late, the penalty is ten
        percent of the scheduled amount plus daily interest of 0.05 percent
        of the scheduled amount for each day late, each of the two components
        rounded half-up to whole cents separately before they are summed."

        Design: Difficulty/combinatorial_formula/late_deposit_penalty_tiered_nonlinear
        """
        _ctx, _a08, _b08, dep_a09 = self._setup_two_periods()
        admin = new_admin_headers()
        validate_success(api.set_clock("2026-10-15T00:00:00Z", admin))
        paid = validate_success(
            api.pay_deposit(dep_a09["id"], 10000, new_analyst_headers()))
        # due 2026-09-25, paid 2026-10-15 = 20 days late:
        # 10% of 10000 = 1000; interest round_half_up(10000*0.0005*20) = 100.
        assert paid["penalty_cents"] == 1100


class TestDepositPenaltyBoundary:
    def _setup_september(self):
        ctx = setup_active_registration()
        create_rated_event(ctx["registration"], ctx["jurisdiction"],
                           ctx["product_class"],
                           event_date="2026-09-05T00:00:00Z",
                           quantity_units=1000)
        deps = list_period_deposits(ctx["registration"]["id"], "2026-09")
        return ctx, deps[0], deps[1]

    def test_deposit_penalty_day5_boundary_inclusive(self, api):
        """PRD §3.7: "Paid one to five days late — five days exactly still
        falls inside this tier — the penalty is two percent of the scheduled
        amount, rounded half-up to a whole cent."

        Design: Difficulty/boundary_precision_check/deposit_penalty_day5_vs_day6_boundary
        """
        _ctx, dep_a, _dep_b = self._setup_september()
        validate_success(
            api.set_clock("2026-09-30T00:00:00Z", new_admin_headers()))
        paid = validate_success(
            api.pay_deposit(dep_a["id"], 10000, new_analyst_headers()))
        # due 2026-09-25, paid 2026-09-30: exactly 5 days, 2% tier.
        assert paid["penalty_cents"] == 200

    def test_deposit_penalty_day6_enters_higher_tier(self, api):
        """PRD §3.7: "Paid six to fifteen days late, the penalty is five
        percent, rounded half-up."

        Design: Difficulty/boundary_precision_check/deposit_penalty_day5_vs_day6_boundary
        """
        _ctx, _dep_a, dep_b = self._setup_september()
        validate_success(
            api.set_clock("2026-10-16T00:00:00Z", new_admin_headers()))
        paid = validate_success(
            api.pay_deposit(dep_b["id"], 10000, new_analyst_headers()))
        # due 2026-10-10, paid 2026-10-16: exactly 6 days, 5% tier.
        assert paid["penalty_cents"] == 500


class TestDepositSweepLateMarking:
    def test_deposit_marked_late_by_sweep(self, api):
        """PRD §3.7: "A deposit that stays unpaid past its `due_date` is
        marked `LATE` by the clock sweep." (On the due date itself it is not
        yet past due.)

        Design: Corner/state_machines/deposit_marked_late_by_sweep
        """
        ctx, _ev, _ret = setup_return_with_rated_event(quantity_units=100)
        dep_a = list_period_deposits(ctx["registration"]["id"], "2026-08")[0]
        assert dep_a["due_date"].startswith("2026-08-25")
        admin = new_admin_headers()

        validate_success(api.set_clock("2026-08-25T00:00:00Z", admin))
        on_due = validate_success(api.get_deposit(dep_a["id"], admin))
        assert on_due["status"] == "SCHEDULED"

        validate_success(api.set_clock("2026-08-26T00:00:00Z", admin))
        late = validate_success(api.get_deposit(dep_a["id"], admin))
        assert late["status"] == "LATE"


class TestSafeHarborPriorPeriod:
    def test_safe_harbor_schedule_uses_prior_filed_return(self, api):
        """PRD §3.7: "Under the `SAFE_HARBOR` variant, the scheduled amount is
        a forward-looking estimate known immediately at return creation: one
        half of the prior period's final `taxable_tax_cents`, rounded half-up
        to whole cents".

        Design: Corner/calculations/safe_harbor_schedule_uses_prior_filed_return
        """
        ctx, _ev, _filed = setup_filed_return()  # 2026-08 taxable 24300
        create_rated_event(ctx["registration"], ctx["jurisdiction"],
                           ctx["product_class"],
                           event_date="2026-09-05T00:00:00Z",
                           quantity_units=10)
        deps = list_period_deposits(ctx["registration"]["id"], "2026-09")
        assert deps[0]["scheduled_amount_cents"] == 12150, (
            "round_half_up(0.5 x 24300)")
        assert deps[1]["scheduled_amount_cents"] == 12150


class TestActualWindowSplit:
    def test_actual_deposit_window_split_by_event_date(self, api):
        """PRD §3.7: "window `A` covers days 1 through 15 of the month and
        falls due on the twenty-fifth of the same month, while window `B`
        covers day 16 through month end and falls due on the tenth of the
        next month" and "the clock sweep at each window close sets the
        scheduled amount to the sum of `tax_cents` over the registration's
        events in that jurisdiction whose `event_date` falls inside the
        window".

        Design: Corner/calculations/actual_deposit_window_split_by_event_date
        """
        ctx = setup_active_registration(deposit_method="ACTUAL")
        create_rated_event(ctx["registration"], ctx["jurisdiction"],
                           ctx["product_class"], quantity_units=1000)
        create_rated_event(ctx["registration"], ctx["jurisdiction"],
                           ctx["product_class"],
                           event_date="2026-08-20T00:00:00Z",
                           quantity_units=1000)
        deps = list_period_deposits(ctx["registration"]["id"], "2026-08")
        dep_a, dep_b = deps[0], deps[1]
        admin = new_admin_headers()

        validate_success(api.set_clock("2026-08-16T00:00:00Z", admin))
        a1 = validate_success(api.get_deposit(dep_a["id"], admin))
        b1 = validate_success(api.get_deposit(dep_b["id"], admin))
        assert a1["scheduled_amount_cents"] == 24300, (
            "window A closed: the 2026-08-03 event accumulates")
        assert b1["scheduled_amount_cents"] == 0, (
            "window B has not closed yet")

        validate_success(api.set_clock("2026-09-01T00:00:00Z", admin))
        b2 = validate_success(api.get_deposit(dep_b["id"], admin))
        assert b2["scheduled_amount_cents"] == 24300, (
            "window B closed: the 2026-08-20 event accumulates")


class TestPinnedSettlementOrder:
    def _setup_overpaid_deposit(self, api, pay_amount):
        """4000-unit SPIRITS event (tax 100000) + depA paid `pay_amount`."""
        ctx, ev, ret = setup_return_with_rated_event(
            product_class_code="SPIRITS", rate_millicents=25000,
            event_overrides={"quantity_units": 4000})
        dep_a = list_period_deposits(ctx["registration"]["id"], "2026-08")[0]
        validate_success(
            api.pay_deposit(dep_a["id"], pay_amount, new_analyst_headers()))
        validate_success(api.submit_return(ret["id"], new_analyst_headers()))
        return ctx, ev, ret, dep_a

    def test_deposit_cap_ignores_penalty_overpaid_settles(self, api):
        """PRD §3.6: "a remaining-need figure starts at the taxable tax minus
        credits, and each deposit in turn contributes the smaller of its
        `paid_amount_cents` and the remaining need" — the cap is computed
        before penalties exist, so 100500 paid against 100000 tax applies
        100000, and "Fourth, penalties are computed" only afterwards (zero
        here: 100000 >= ninety percent of the tax).

        Design: Difficulty/combinatorial_formula/return_settlement_pinned_evaluation_order
        """
        _ctx, _ev, ret, dep_a = self._setup_overpaid_deposit(api, 100500)
        filed = file_return(ret["id"])
        assert filed["deposits_applied_cents"] == 100000, (
            "capped at taxable tax minus credits, not at the amount paid")
        assert filed["penalty_cents"] == 0
        assert filed["net_due_cents"] == 0
        assert filed["settlement_status"] == "SETTLED"

        dep = validate_success(api.get_deposit(dep_a["id"], new_analyst_headers()))
        assert dep["status"] == "APPLIED"
        assert dep["applied_amount_cents"] == 100000

    def test_deposit_excess_flows_to_overpayment_balance(self, api):
        """PRD §3.6: "any paid cash beyond the portion taken flows into the
        registrant's `overpayment_balance_cents`."

        Design: Difficulty/combinatorial_formula/return_settlement_pinned_evaluation_order
        """
        ctx, _ev, ret, _dep_a = self._setup_overpaid_deposit(api, 100500)
        file_return(ret["id"])
        rgt = validate_success(
            api.get_registrant(ctx["registrant"]["id"], new_analyst_headers()))
        assert rgt["overpayment_balance_cents"] == 500, (
            "100500 paid - 100000 applied")


class TestUnderpaymentSafeHarborBoundary:
    def _setup_two_jurisdiction_pair(self):
        ca = setup_active_registration(
            product_class_code="SPIRITS", rate_millicents=25000,
            jurisdiction_overrides={"code": "CA-BOE", "name": "California"})
        nv = setup_active_registration(
            product_class_code="SPIRITS", rate_millicents=25000,
            jurisdiction_overrides={"code": "NV-TX", "name": "Nevada"})
        return ca, nv

    def _rate_and_pay(self, api, ctx, pay_amount):
        _ev = create_rated_event(ctx["registration"], ctx["jurisdiction"],
                                 ctx["product_class"], quantity_units=4000)
        ret_id = _ev["return_id"]
        dep_a = list_period_deposits(ctx["registration"]["id"], "2026-08")[0]
        validate_success(
            api.pay_deposit(dep_a["id"], pay_amount, new_analyst_headers()))
        validate_success(api.submit_return(ret_id, new_analyst_headers()))
        return ret_id

    def test_underpayment_safe_harbor_exact_90_no_penalty(self, api):
        """PRD §3.6: "an underpayment penalty applies when the taxable tax is
        positive and the deposits applied fall short of ninety percent of the
        taxable tax rounded up to the next whole cent" — deposits equal to
        exactly ninety percent (90000 of 100000) do not fall short.

        Design: Difficulty/boundary_precision_check/underpayment_safe_harbor_exact_90_percent
        """
        ca, _nv = self._setup_two_jurisdiction_pair()
        ret_id = self._rate_and_pay(api, ca, 90000)
        filed = file_return(ret_id)
        assert filed["deposits_applied_cents"] == 90000
        assert filed["penalty_cents"] == 0, (
            "exactly at the ninety-percent safe harbor: no penalty")
        assert filed["net_due_cents"] == 10000

    def test_underpayment_one_cent_below_triggers_penalty(self, api):
        """PRD §3.6: "the penalty is ten percent of the difference between
        the taxable tax and the deposits applied, rounded half-up" — one cent
        below the safe harbor (89999 of 100000) yields
        round_half_up(0.10 x 10001) == 1000.

        Design: Difficulty/boundary_precision_check/underpayment_safe_harbor_exact_90_percent
        """
        _ca, nv = self._setup_two_jurisdiction_pair()
        ret_id = self._rate_and_pay(api, nv, 89999)
        filed = file_return(ret_id)
        assert filed["deposits_applied_cents"] == 89999
        assert filed["penalty_cents"] == 1000
        assert filed["net_due_cents"] == 11001


class TestDepositWaterfallConservation:
    def test_deposit_waterfall_caps_applied_at_remaining_need(self, api):
        """PRD §3.6: "each deposit in turn contributes the smaller of its
        `paid_amount_cents` and the remaining need — that portion becomes the
        deposit's `applied_amount_cents`".

        Design: Difficulty/compensating_invariant/deposit_waterfall_conserves_cash
        """
        ctx, ev, ret = setup_return_with_rated_event(
            product_class_code="SPIRITS", rate_millicents=25000,
            event_overrides={"quantity_units": 4000})  # tax 100000
        dep_a = list_period_deposits(ctx["registration"]["id"], "2026-08")[0]
        validate_success(
            api.pay_deposit(dep_a["id"], 120000, new_analyst_headers()))
        validate_success(api.submit_return(ret["id"], new_analyst_headers()))
        filed = file_return(ret["id"])
        assert filed["deposits_applied_cents"] == 100000
        assert filed["net_due_cents"] == 0

        dep = validate_success(api.get_deposit(dep_a["id"], new_analyst_headers()))
        assert dep["paid_amount_cents"] == 120000
        assert dep["applied_amount_cents"] == 100000

    def test_deposit_waterfall_conserves_paid_cash(self, api):
        """PRD §3.6: "any paid cash beyond the portion taken flows into the
        registrant's `overpayment_balance_cents`" — paid (120000) == applied
        (100000) + overpayment contribution (20000).

        Design: Difficulty/compensating_invariant/deposit_waterfall_conserves_cash
        """
        ctx, ev, ret = setup_return_with_rated_event(
            product_class_code="SPIRITS", rate_millicents=25000,
            event_overrides={"quantity_units": 4000})
        dep_a = list_period_deposits(ctx["registration"]["id"], "2026-08")[0]
        validate_success(
            api.pay_deposit(dep_a["id"], 120000, new_analyst_headers()))
        validate_success(api.submit_return(ret["id"], new_analyst_headers()))
        file_return(ret["id"])
        rgt = validate_success(
            api.get_registrant(ctx["registrant"]["id"], new_analyst_headers()))
        assert rgt["overpayment_balance_cents"] == 20000


class TestLateFilingPenalty:
    def test_late_filing_penalty_stacked_with_underpayment(self, api):
        """PRD §3.6: "a late-filing penalty applies when the filing date
        falls after the `due_date` — five percent of the taxable tax for each
        started thirty-day month of lateness, capped at twenty-five percent
        of the taxable tax, each rounded half-up. The two components sum to
        `penalty_cents`."

        Design: Corner/calculations/late_filing_penalty_stacked_with_underpayment
        """
        ctx, _ev, ret = setup_return_with_rated_event()
        validate_success(api.submit_return(ret["id"], new_analyst_headers()))
        # due_date for 2026-08 is 2026-09-25; file at 2026-10-20 (25 days
        # late = one started 30-day month).
        validate_success(
            api.set_clock("2026-10-20T00:00:00Z", new_admin_headers()))
        filed = file_return(ret["id"])
        assert filed["due_date"].startswith("2026-09-25")
        assert filed["penalty_cents"] == 3645, (
            "late 1215 = round_half_up(0.05 x 24300) plus underpayment "
            "2430 = round_half_up(0.10 x 24300)")
        assert filed["net_due_cents"] == 27945


class TestDepositActions:
    def test_deposit_waive_conditional_action(self, api):
        """PRD §3.7: "A `ComplianceAdmin` may instead waive a `SCHEDULED` or
        `LATE` deposit, moving it to `WAIVED`." — a `PAID` deposit cannot be
        waived (§2.10 item 5, `ERR_INVALID_STATE`).

        Design: Corner/endpoints/deposit_waive_conditional_action
        """
        ctx, _ev, _ret = setup_return_with_rated_event(quantity_units=100)
        deps = list_period_deposits(ctx["registration"]["id"], "2026-08")
        dep_a, dep_b = deps[0], deps[1]
        validate_success(
            api.pay_deposit(dep_a["id"], 10000, new_analyst_headers()))
        admin = new_admin_headers()

        resp_paid = api.waive_deposit(dep_a["id"], admin)
        validate_error(resp_paid, ApiErrorId.ERR_INVALID_STATE)

        waived = validate_success(api.waive_deposit(dep_b["id"], admin))
        assert waived["status"] == "WAIVED"

    def test_pay_applied_deposit_rejected(self, api):
        """PRD §3.7: "each `PAID` deposit of the period transitions to
        `APPLIED` with `applied_return_id` set to the filed return" — payment
        is valid only "on a `SCHEDULED` or `LATE` deposit", so a second pay
        on an `APPLIED` deposit fails `ERR_INVALID_STATE` per §2.10 item 5.

        Design: Corner/state_machines/pay_applied_deposit_rejected
        """
        ctx, _ev, ret = setup_return_with_rated_event()
        dep_a = list_period_deposits(ctx["registration"]["id"], "2026-08")[0]
        validate_success(
            api.pay_deposit(dep_a["id"], 24300, new_analyst_headers()))
        validate_success(api.submit_return(ret["id"], new_analyst_headers()))
        file_return(ret["id"])

        dep = validate_success(api.get_deposit(dep_a["id"], new_analyst_headers()))
        assert dep["status"] == "APPLIED"
        resp = api.pay_deposit(dep_a["id"], 100, new_analyst_headers())
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestFilingImmediateConsistency:
    def test_filing_response_reflects_final_state_immediately(self, api):
        """PRD §3.6: "Filing stamps `filed_at` with the logical clock,
        records `filed_by_user_id`, and computes settlement in a pinned
        evaluation order" and "The settlement status is then set from the
        sign of the net due: positive leaves the return `AWAITING_PAYMENT`".
        PRD §2.2: "operations that create or modify a resource will return
        the created or updated resource object in the data field."

        Design: Corner/consistency_model/filing_response_reflects_final_state_immediately
        """
        ctx, _ev, ret = setup_return_with_rated_event()
        validate_success(api.submit_return(ret["id"], new_analyst_headers()))
        version = validate_success(
            api.get_return(ret["id"], new_reviewer_headers()))["version"]
        body = validate_success(api.file_return(
            ret["id"], version, new_reviewer_headers()))
        assert body["filing_status"] == "FILED"
        assert body["penalty_cents"] == 2430
        assert body["net_due_cents"] == 26730
        assert body["settlement_status"] == "AWAITING_PAYMENT"
        assert body["filed_at"].startswith("2026-08-01T00:00:00"), (
            "filed_at is stamped with the logical clock at filing time")
