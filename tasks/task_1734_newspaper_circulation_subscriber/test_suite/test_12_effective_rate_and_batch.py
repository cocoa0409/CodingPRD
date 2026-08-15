"""Effective weekly rate: tenure step-up boundaries and save-discount floor."""
from test_helpers import (
    DIRECTOR,
    REP,
    cancel_and_get_offer,
    create_plan,
    create_subscriber,
    create_subscription,
    get_subscription,
    list_charges_for_subscription,
    pay_and_clear,
    run_daily_cycle,
    set_clock,
    set_clock_and_cycle,
    validate_success,
)


class TestStepUpBoundary:
    def test_rate_stepup_inclusive_week_boundary(self, api):
        """PRD §3.1: "The rate starts at the plan's `base_weekly_rate_cents`,
        then walks the `step_up_schedule` in ascending `after_weeks` order:
        any step whose `after_weeks` threshold has been reached by the
        current tenure — including exactly reached, since the boundary is
        inclusive — replaces the running rate with that step's
        `weekly_rate_cents`."

        Design: Difficulty/boundary_precision_check/rate_stepup_inclusive_week_boundary
        """
        # Default startup clock 2026-08-01; backdated start 2026-01-05.
        plan = create_plan(
            name="STEPB", plan_type="DIGITAL", issues_per_week=0,
            base_weekly_rate_cents=600,
            step_up_schedule=[
                {"after_weeks": 12, "weekly_rate_cents": 800},
                {"after_weeks": 26, "weekly_rate_cents": 1000},
            ],
            proration_method="PER_DAY", min_weekly_rate_cents=0,
        )
        subscriber = create_subscriber(display_name="B1", email="b1@x.com")
        subscription = create_subscription(subscriber["id"], plan["id"], start_date="2026-01-05")

        run_daily_cycle()  # catch-up: periods 2026-01-05 .. 2026-07-27

        charges = list_charges_for_subscription(subscription["id"])
        assert len(charges) >= 27, (
            f"Setup failed: expected at least 27 catch-up charges, got {len(charges)}"
        )
        # Charges are ordered by period_start ASC (list contract, PRD §2.3).
        assert charges[11]["period_start"] == "2026-03-23"
        assert charges[11]["amount_cents"] == 600, "tenure 11 weeks < 12: base rate"
        assert charges[12]["period_start"] == "2026-03-30"
        assert charges[12]["amount_cents"] == 800, "tenure exactly 12 weeks: step applies"
        assert charges[25]["period_start"] == "2026-06-29"
        assert charges[25]["amount_cents"] == 800, "tenure 25 weeks < 26: first step"
        assert charges[26]["period_start"] == "2026-07-06"
        assert charges[26]["amount_cents"] == 1000, "tenure exactly 26 weeks: second step"

    def test_rate_stepup_below_first_step_keeps_base_rate(self, api):
        """PRD §3.1: "Tenure in whole weeks is measured from the
        subscription's `start_date` to the charge's `period_start` — that is,
        the difference in days divided by seven, rounded down. The rate
        starts at the plan's `base_weekly_rate_cents`, then walks the
        `step_up_schedule` in ascending `after_weeks` order: any step whose
        `after_weeks` threshold has been reached by the current tenure —
        including exactly reached, since the boundary is inclusive —
        replaces the running rate with that step's `weekly_rate_cents`."

        Design: Difficulty/boundary_precision_check/rate_stepup_inclusive_week_boundary
        """
        plan = create_plan(
            name="STEP0", plan_type="DIGITAL", issues_per_week=0,
            base_weekly_rate_cents=600,
            step_up_schedule=[{"after_weeks": 4, "weekly_rate_cents": 900}],
            proration_method="PER_DAY", min_weekly_rate_cents=0,
        )
        subscriber = create_subscriber(display_name="B0", email="b0@x.com")
        subscription = create_subscription(subscriber["id"], plan["id"], start_date="2026-07-06")
        # Clocks: 07-06 (tenure 0), 07-13 (1), 07-20 (2), 07-27 (3), 08-03 (4).
        run_daily_cycle()
        for clock in ("2026-07-13T00:00:00Z", "2026-07-20T00:00:00Z",
                      "2026-07-27T00:00:00Z", "2026-08-03T00:00:00Z"):
            set_clock_and_cycle(clock)

        charges = list_charges_for_subscription(subscription["id"])
        assert [c["amount_cents"] for c in charges] == [600, 600, 600, 600, 900], (
            "the step applies only from tenure week 4 onward (inclusive)"
        )


class TestSaveDiscountInteraction:
    def test_save_discount_floor_and_tiered_step_interaction(self, api):
        """PRD §3.1: "If the subscription carries an accepted save discount
        and the charge's `period_start` falls strictly before
        `save_discount_until`, the stepped rate is multiplied by one minus
        `save_discount_pct`, rounded half up to the nearest cent, and the
        result is floored at the plan's `min_weekly_rate_cents`."
        PRD §3.5: "Accepting flips the offer to `ACCEPTED`, writes
        `save_discount_pct` onto the subscription, sets `save_discount_until`
        to today plus the offer's duration in weeks times seven days (the
        discount applies to charges whose period starts strictly before that
        date), clears the `cancel_reason`, rescues a `CANCEL_PENDING`
        subscription back to `ACTIVE`, and increments the subscription's
        `version`."

        Design: Difficulty/combinatorial_formula/save_discount_floor_and_tiered_step_interaction
        """
        set_clock("2026-08-03T00:00:00Z")
        plan = create_plan(
            name="STEP", plan_type="PRINT", issues_per_week=7,
            base_weekly_rate_cents=600,
            step_up_schedule=[{"after_weeks": 4, "weekly_rate_cents": 800}],
            proration_method="PER_DAY", min_weekly_rate_cents=500,
        )
        subscriber = create_subscriber(
            display_name="S", email="s@x.com", service_address="6 Main St"
        )
        subscription = create_subscription(subscriber["id"], plan["id"], start_date="2026-08-03")
        run_daily_cycle()

        # Keep the account current through week 4 (four 600 charges, then
        # the week-4 stepped 800 charge).
        pay_and_clear(subscriber["id"], 600)
        set_clock_and_cycle("2026-08-10T00:00:00Z")
        pay_and_clear(subscriber["id"], 600)
        set_clock_and_cycle("2026-08-17T00:00:00Z")
        pay_and_clear(subscriber["id"], 600)
        set_clock_and_cycle("2026-08-24T00:00:00Z")
        pay_and_clear(subscriber["id"], 600)
        set_clock_and_cycle("2026-08-31T00:00:00Z")
        pay_and_clear(subscriber["id"], 800)  # tenure week 4 -> stepped rate

        current = get_subscription(subscription["id"])
        offer = validate_success(
            api.create_save_offer(
                subscription["id"],
                {
                    "discount_pct": 0.5,
                    "duration_weeks": 8,
                    "expected_subscription_version": current["version"],
                },
                REP,
            ),
            201,
        )
        accepted = validate_success(api.accept_save_offer(offer["id"], REP))
        assert accepted["status"] == "ACCEPTED"

        updated = get_subscription(subscription["id"])
        assert updated["save_discount_until"] == "2026-10-26"  # 2026-08-31 + 8*7

        # Week-5 charge: stepped 800, discounted to 400, floored to 500.
        set_clock_and_cycle("2026-09-07T00:00:00Z")
        charges = list_charges_for_subscription(subscription["id"])
        week5 = [c for c in charges if c["period_start"] == "2026-09-07"]
        assert len(week5) == 1, "Setup failed: expected the week-5 charge"
        assert week5[0]["amount_cents"] == 500, (
            "round_half_up(800 * 0.5) = 400, floored at min_weekly_rate_cents 500"
        )

    def test_save_discount_applies_off_stepped_rate_not_base(self, api):
        """PRD §3.1: "If the subscription carries an accepted save discount
        and the charge's `period_start` falls strictly before
        `save_discount_until`, the stepped rate is multiplied by one minus
        `save_discount_pct`, rounded half up to the nearest cent, and the
        result is floored at the plan's `min_weekly_rate_cents`."

        Design: Difficulty/combinatorial_formula/save_discount_floor_and_tiered_step_interaction
        """
        set_clock("2026-08-03T00:00:00Z")
        plan = create_plan(
            name="STEP2", plan_type="DIGITAL", issues_per_week=0,
            base_weekly_rate_cents=600,
            step_up_schedule=[{"after_weeks": 2, "weekly_rate_cents": 1000}],
            proration_method="PER_DAY", min_weekly_rate_cents=0,
        )
        subscriber = create_subscriber(display_name="S2", email="s2@x.com")
        subscription = create_subscription(subscriber["id"], plan["id"], start_date="2026-08-03")
        run_daily_cycle()
        pay_and_clear(subscriber["id"], 600)
        set_clock_and_cycle("2026-08-10T00:00:00Z")
        pay_and_clear(subscriber["id"], 600)

        # Accept a 25% save offer on 2026-08-10 (before the week-2 charge).
        current = get_subscription(subscription["id"])
        offer = validate_success(
            api.create_save_offer(
                subscription["id"],
                {
                    "discount_pct": 0.25,
                    "duration_weeks": 4,
                    "expected_subscription_version": current["version"],
                },
                REP,
            ),
            201,
        )
        validate_success(api.accept_save_offer(offer["id"], REP))

        # Week-2 charge (period 2026-08-17): stepped 1000 * 0.75 = 750.
        set_clock_and_cycle("2026-08-17T00:00:00Z")
        charges = list_charges_for_subscription(subscription["id"])
        week2 = [c for c in charges if c["period_start"] == "2026-08-17"]
        assert len(week2) == 1
        assert week2[0]["amount_cents"] == 750, (
            "discount multiplies the stepped rate (1000), not the base rate (600)"
        )


class TestDailyCycleSummary:
    def test_daily_cycle_output_summary(self, api):
        """PRD §2.5: "The batch returns a summary object with counts:
        `activated_subscriptions`, `holds_activated`, `holds_completed`,
        `charges_generated`, `offers_expired`, `status_changes`, and
        `plan_changes_applied`."

        Design: Corner/endpoints/daily_cycle_output_summary
        """
        # Default startup clock is 2026-08-01 (PRD §2.5).
        plan = create_plan(
            name="CS", plan_type="DIGITAL", issues_per_week=0,
            base_weekly_rate_cents=500, proration_method="PER_DAY",
            min_weekly_rate_cents=0,
        )
        subscriber = create_subscriber(display_name="CS", email="cs@x.com")
        create_subscription(subscriber["id"], plan["id"], start_date="2026-08-01")

        summary = validate_success(api.run_daily_cycle(DIRECTOR))
        assert summary["activated_subscriptions"] == 1
        assert summary["charges_generated"] == 1
        assert summary["holds_completed"] == 0
        assert summary["offers_expired"] == 0
        assert summary["plan_changes_applied"] == 0

    def test_daily_cycle_summary_counts_offer_expiry(self, api):
        """PRD §2.5: "The nightly batch is an explicit, director-invoked
        operation that runs seven steps in a pinned order against the current
        logical date: (1) activate `PENDING_START` subscriptions whose
        `start_date` has been reached, generating their first weekly charge
        immediately in a catch-up loop; (2) activate `SCHEDULED` vacation
        holds whose start has arrived; (3) complete `ACTIVE` holds whose end
        has arrived, issuing proration credits where the resolution calls for
        them; (4) run the weekly charge catch-up for subscriptions in
        `ACTIVE`, `GRACE`, or `CANCEL_PENDING`; (5) expire `OFFERED` save
        offers past their `expires_at`, churning `CANCEL_PENDING`
        subscriptions to `CANCELLED`; (6) re-evaluate the lapse cycle across
        all non-terminal subscriptions; (7) apply pending plan changes whose
        `effective_date` has arrived."

        Design: Corner/endpoints/daily_cycle_output_summary
        """
        from test_helpers import setup_cancel_pending
        ctx = setup_cancel_pending(
            start_date="2026-08-03", clock="2026-08-03T00:00:00Z"
        )
        # Offer expires 2026-08-10 (seven days out from 2026-08-03).
        set_clock("2026-08-10T00:00:00Z")
        summary = run_daily_cycle()
        assert summary["offers_expired"] == 1
