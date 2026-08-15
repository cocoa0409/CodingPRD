"""Subscription activation, lapse-cycle boundaries, bubble-up, terminal lockdown."""
from test_helpers import (
    DIRECTOR,
    REP,
    ApiErrorId,
    cancel_and_get_offer,
    create_active_subscription,
    create_plan,
    create_subscriber,
    create_subscription,
    get_subscriber,
    get_subscription,
    list_charges_for_subscription,
    run_daily_cycle,
    set_clock,
    set_clock_and_cycle,
    setup_cancel_pending,
    validate_error,
    validate_success,
)


class TestActivation:
    def test_subscription_activation_valid_transition(self, api):
        """PRD §3.1: "When the daily cycle finds a `PENDING_START`
        subscription whose `start_date` has arrived, it flips billing to
        `ACTIVE`, sets `next_charge_date` to the start date, immediately
        generates the first weekly charge, and — if the plan is print-capable
        (`PRINT` or `BUNDLE`) — flips delivery from `NOT_DELIVERED` to
        `DELIVERING`."
        PRD §3.1: "Each generated charge records a weekly `period_start`, a
        `period_end` seven days later, a `due_date` fourteen days after the
        period start, and an `amount_cents` equal to the effective weekly
        rate at generation time."

        Design: Corner/state_machines/subscription_activation_valid_transition
        """
        set_clock("2026-08-03T00:00:00Z")
        plan = create_plan(
            name="ACT", plan_type="PRINT", issues_per_week=7,
            base_weekly_rate_cents=600, proration_method="PER_DAY",
            min_weekly_rate_cents=0,
        )
        subscriber = create_subscriber(
            display_name="A", email="act@x.com", service_address="1 Oak St"
        )
        created = create_subscription(subscriber["id"], plan["id"], start_date="2026-08-03")
        assert created["billing_status"] == "PENDING_START"

        run_daily_cycle()

        after = get_subscription(created["id"])
        assert after["billing_status"] == "ACTIVE"
        assert after["delivery_status"] == "DELIVERING"

        charges = list_charges_for_subscription(created["id"])
        assert len(charges) == 1
        assert charges[0]["amount_cents"] == 600
        assert charges[0]["period_start"] == "2026-08-03"
        assert charges[0]["due_date"] == "2026-08-17"

    def test_subscription_activation_digital_stays_not_delivered(self, api):
        """PRD §3.1: "When the daily cycle finds a `PENDING_START`
        subscription whose `start_date` has arrived, it flips billing to
        `ACTIVE`, sets `next_charge_date` to the start date, immediately
        generates the first weekly charge, and — if the plan is print-capable
        (`PRINT` or `BUNDLE`) — flips delivery from `NOT_DELIVERED` to
        `DELIVERING`."

        Design: Corner/state_machines/subscription_activation_valid_transition
        """
        ctx = create_active_subscription(
            start_date="2026-08-03",
            clock="2026-08-03T00:00:00Z",
            plan_overrides={
                "name": "ACTD", "plan_type": "DIGITAL", "issues_per_week": 0,
                "base_weekly_rate_cents": 400,
            },
        )
        assert ctx["subscription"]["billing_status"] == "ACTIVE"
        assert ctx["subscription"]["delivery_status"] == "NOT_DELIVERED", (
            "digital plans have no delivery leg to activate"
        )


class TestLapseThresholdBoundaries:
    def test_lapse_threshold_strictly_greater_boundaries(self, api):
        """PRD §3.2: "That single number drives the billing axis with
        strictly-greater thresholds — so a charge exactly seven days past due
        leaves the subscription in good standing"
        PRD §3.2: "More than forty-five days: the subscription lapses to the
        terminal `LAPSED`. Every `OPEN` or `PARTIALLY_PAID` charge on the
        subscription is written off, delivery is forced to `NOT_DELIVERED`,
        `ended_at` is stamped with the current date, and the owning
        subscriber's bubble-up is re-evaluated."

        Design: Corner/calculations/lapse_threshold_strictly_greater_boundaries
        """
        set_clock("2026-07-06T00:00:00Z")
        plan = create_plan(
            name="LT", plan_type="DIGITAL", issues_per_week=0,
            base_weekly_rate_cents=600, proration_method="PER_DAY",
            min_weekly_rate_cents=0,
        )
        subscriber = create_subscriber(display_name="LT", email="lt@x.com")
        subscription = create_subscription(subscriber["id"], plan["id"], start_date="2026-07-06")
        run_daily_cycle()

        # First charge: period 2026-07-06, due 2026-07-20 (TERMS_DAYS 14).
        expectations = [
            ("2026-07-27T00:00:00Z", "ACTIVE"),     # exactly 7 days past due
            ("2026-07-28T00:00:00Z", "GRACE"),      # 8 days
            ("2026-08-10T00:00:00Z", "GRACE"),      # exactly 21 days
            ("2026-08-11T00:00:00Z", "SUSPENDED"),  # 22 days
            ("2026-09-03T00:00:00Z", "SUSPENDED"),  # exactly 45 days
            ("2026-09-04T00:00:00Z", "LAPSED"),     # 46 days
        ]
        for clock, expected in expectations:
            set_clock_and_cycle(clock)
            status = get_subscription(subscription["id"])["billing_status"]
            assert status == expected, (
                f"at clock {clock} expected billing_status {expected}, got {status}"
            )

    def test_lapse_terminal_write_off(self, api):
        """PRD §3.2: "More than forty-five days: the subscription lapses to
        the terminal `LAPSED`. Every `OPEN` or `PARTIALLY_PAID` charge on the
        subscription is written off, delivery is forced to `NOT_DELIVERED`,
        `ended_at` is stamped with the current date, and the owning
        subscriber's bubble-up is re-evaluated."
        PRD §2.7: "`CANCELLED` and `LAPSED` are terminal — once reached, they
        are never re-entered."

        Design: Corner/calculations/lapse_threshold_strictly_greater_boundaries
        """
        set_clock("2026-07-06T00:00:00Z")
        plan = create_plan(
            name="LT2", plan_type="DIGITAL", issues_per_week=0,
            base_weekly_rate_cents=600, proration_method="PER_DAY",
            min_weekly_rate_cents=0,
        )
        subscriber = create_subscriber(display_name="LT2", email="lt2@x.com")
        subscription = create_subscription(subscriber["id"], plan["id"], start_date="2026-07-06")
        run_daily_cycle()

        set_clock_and_cycle("2026-09-04T00:00:00Z")  # 46 days past due
        after = get_subscription(subscription["id"])
        assert after["billing_status"] == "LAPSED"
        assert after["ended_at"] == "2026-09-04"

        charges = list_charges_for_subscription(subscription["id"])
        assert charges, "Setup failed: expected generated charges"
        for charge in charges:
            assert charge["status"] == "WRITTEN_OFF"


class TestSubscriberBubbleUpAndClose:
    def test_subscriber_compound_bubble_to_lapsed_and_close(self, api):
        """PRD §3.2: "The subscriber-level **bubble-up** ties the axes to the
        account: when every subscription on a subscriber has reached a
        terminal billing state (`CANCELLED` or `LAPSED`) and at least one
        subscription exists, the subscriber's `status` flips from `ACTIVE` to
        `LAPSED`."
        PRD §2.6: "Charges in `WRITTEN_OFF` status are excluded from the
        balance entirely."

        Design: Corner/state_machines/subscriber_compound_bubble_to_lapsed_and_close
        """
        # Default startup clock is 2026-08-01; a subscription backdated to
        # 2026-05-04 has its first charge due 2026-05-18 — 75 days past due.
        plan = create_plan(
            name="BL", plan_type="DIGITAL", issues_per_week=0,
            base_weekly_rate_cents=600, proration_method="PER_DAY",
            min_weekly_rate_cents=0,
        )
        subscriber = create_subscriber(display_name="BL", email="bl@x.com")
        subscription = create_subscription(subscriber["id"], plan["id"], start_date="2026-05-04")

        run_daily_cycle()

        sub_after = get_subscription(subscription["id"])
        assert sub_after["billing_status"] == "LAPSED"
        charges = list_charges_for_subscription(subscription["id"])
        assert charges and all(c["status"] == "WRITTEN_OFF" for c in charges)

        subscriber_after = get_subscriber(subscriber["id"])
        assert subscriber_after["status"] == "LAPSED"
        assert subscriber_after["balance_due_cents"] == 0

        closed = validate_success(api.close_subscriber(subscriber["id"], REP))
        assert closed["status"] == "CLOSED"

    def test_close_lapsed_subscriber_with_open_balance_rejected(self, api):
        """PRD §3.2: "Closing the account entirely is a deliberate act: a
        `ServiceRep` or `CirculationDirector` may close a `LAPSED` subscriber
        only when the ledger is fully settled — `balance_due_cents` of zero
        and `unapplied_cash_cents` of zero — otherwise the close is rejected
        with `ERR_SUBSCRIBER_NOT_SETTLED`."
        PRD §3.5: "From `SUSPENDED`, no save offer is created at all — the
        subscription churns directly to `CANCELLED`, delivery is forced to
        `NOT_DELIVERED`, `ended_at` is stamped, and the subscriber bubble-up
        re-evaluates."

        Design: Corner/state_machines/subscriber_compound_bubble_to_lapsed_and_close
        """
        # Drive a subscription to SUSPENDED (oldest charge 22 days past due),
        # then cancel directly to CANCELLED; open charges are NOT written off
        # by cancellation, so the bubbled-up LAPSED subscriber still owes.
        set_clock("2026-08-03T00:00:00Z")
        plan = create_plan(
            name="BL2", plan_type="DIGITAL", issues_per_week=0,
            base_weekly_rate_cents=600, proration_method="PER_DAY",
            min_weekly_rate_cents=0,
        )
        subscriber = create_subscriber(display_name="BL2", email="bl2@x.com")
        subscription = create_subscription(subscriber["id"], plan["id"], start_date="2026-08-03")
        run_daily_cycle()
        set_clock_and_cycle("2026-09-08T00:00:00Z")  # 22 days past due -> SUSPENDED
        assert get_subscription(subscription["id"])["billing_status"] == "SUSPENDED"

        cancelled = validate_success(
            api.cancel_subscription(subscription["id"], {"reason": "gone"}, REP)
        )
        assert cancelled["billing_status"] == "CANCELLED"

        subscriber_after = get_subscriber(subscriber["id"])
        assert subscriber_after["status"] == "LAPSED"
        assert subscriber_after["balance_due_cents"] > 0

        resp = api.close_subscriber(subscriber["id"], REP)
        validate_error(resp, ApiErrorId.ERR_SUBSCRIBER_NOT_SETTLED, 409)
