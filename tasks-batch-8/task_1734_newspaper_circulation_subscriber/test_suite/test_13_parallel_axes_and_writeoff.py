"""Parallel billing/delivery axes, charge write-off, service-address gating."""
from test_helpers import (
    DIRECTOR,
    REP,
    ApiErrorId,
    create_active_subscription,
    create_hold,
    create_plan,
    create_subscriber,
    create_subscription,
    list_charges_for_subscription,
    pay_and_clear,
    run_daily_cycle,
    set_clock,
    set_clock_and_cycle,
    validate_error,
    validate_success,
)
from test_helpers import get_subscription


class TestParallelAxes:
    def test_subscription_parallel_billing_delivery_axes(self, api):
        """PRD §2.7: "The axes are independent except in one direction:
        billing transitions can force delivery transitions (suspension stops
        delivery; reinstatement resumes it for print-capable plans;
        cancellation and lapse end it), but a delivery-side change never
        moves the billing axis."
        PRD §3.2: "More than seven but at most twenty-one days: the
        subscription sits in `GRACE`."

        Design: Difficulty/non_linear_state_machine/subscription_parallel_billing_delivery_axes
        """
        set_clock("2026-08-03T00:00:00Z")
        plan = create_plan(
            name="PAR", plan_type="PRINT", issues_per_week=7,
            base_weekly_rate_cents=600, proration_method="PER_DAY",
            min_weekly_rate_cents=0,
        )
        subscriber = create_subscriber(
            display_name="P", email="p@x.com", service_address="7 Main St"
        )
        subscription = create_subscription(subscriber["id"], plan["id"], start_date="2026-08-03")
        run_daily_cycle()

        # 21-day REDELIVER hold keeps delivery HELD across the observation.
        create_hold(subscription["id"], "2026-08-10", "2026-08-31", "REDELIVER")
        set_clock_and_cycle("2026-08-10T00:00:00Z")

        # Oldest charge (due 2026-08-17) is 9 days past due on 2026-08-26.
        set_clock_and_cycle("2026-08-26T00:00:00Z")
        before = get_subscription(subscription["id"])
        assert before["billing_status"] == "GRACE"
        assert before["delivery_status"] == "HELD", (
            "both axes observable at once: billing degraded while the hold persists"
        )

        # Clear all four weekly charges (600 x 4).
        pay_and_clear(subscriber["id"], 2400)
        after = get_subscription(subscription["id"])
        assert after["billing_status"] == "ACTIVE"
        assert after["delivery_status"] == "HELD", (
            "billing recovery must not touch the delivery axis"
        )

    def test_suspension_forces_delivery_stop(self, api):
        """PRD §2.7: "The axes are independent except in one direction:
        billing transitions can force delivery transitions (suspension stops
        delivery; reinstatement resumes it for print-capable plans;
        cancellation and lapse end it), but a delivery-side change never
        moves the billing axis."
        PRD §3.2: "More than twenty-one but at most forty-five days: the
        subscription drops to `SUSPENDED`. Delivery stops — `DELIVERING` or
        `HELD` flips to `NOT_DELIVERED` — and charge generation pauses while
        the subscription remains suspended."

        Design: Difficulty/non_linear_state_machine/subscription_parallel_billing_delivery_axes
        """
        ctx = create_active_subscription(
            start_date="2026-08-03", clock="2026-08-03T00:00:00Z"
        )
        subscription_id = ctx["subscription"]["id"]
        assert ctx["subscription"]["delivery_status"] == "DELIVERING"

        # 22 days past due -> SUSPENDED, delivery forced off.
        set_clock_and_cycle("2026-09-08T00:00:00Z")
        after = get_subscription(subscription_id)
        assert after["billing_status"] == "SUSPENDED"
        assert after["delivery_status"] == "NOT_DELIVERED"

        # Reinstatement: clearing everything returns billing to ACTIVE and
        # resumes delivery for the print-capable plan.
        charges = list_charges_for_subscription(subscription_id)
        total_due = sum(
            c["amount_cents"] - c["paid_amount_cents"] - c["credit_applied_cents"]
            for c in charges
        )
        pay_and_clear(ctx["subscriber"]["id"], total_due)
        reinstated = get_subscription(subscription_id)
        assert reinstated["billing_status"] == "ACTIVE"
        assert reinstated["delivery_status"] == "DELIVERING"


class TestChargeWriteOff:
    def test_write_off_paid_charge_rejected(self, api):
        """PRD §3.8: "Charges themselves can be forgiven directly: a
        `CirculationDirector` may write off a charge in `OPEN` or
        `PARTIALLY_PAID` status (anything else draws `ERR_CHARGE_NOT_OPEN`),
        flipping it to `WRITTEN_OFF` and excluding it from the
        `balance_due_cents` aggregation forever after."

        Design: Corner/errors/write_off_paid_charge_rejected
        """
        ctx = create_active_subscription(
            start_date="2026-08-03",
            clock="2026-08-03T00:00:00Z",
            plan_overrides={
                "name": "WO", "plan_type": "DIGITAL", "issues_per_week": 0,
                "base_weekly_rate_cents": 600,
            },
        )
        pay_and_clear(ctx["subscriber"]["id"], 600)
        charge = list_charges_for_subscription(ctx["subscription"]["id"])[0]
        assert charge["status"] == "PAID"

        resp = api.write_off_billing_charge(charge["id"], DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_CHARGE_NOT_OPEN, 409)

    def test_write_off_open_charge_excluded_from_balance(self, api):
        """PRD §3.8: "Charges themselves can be forgiven directly: a
        `CirculationDirector` may write off a charge in `OPEN` or
        `PARTIALLY_PAID` status (anything else draws `ERR_CHARGE_NOT_OPEN`),
        flipping it to `WRITTEN_OFF` and excluding it from the
        `balance_due_cents` aggregation forever after."
        PRD §2.6: "Charges in `WRITTEN_OFF` status are excluded from the
        balance entirely."

        Design: Corner/errors/write_off_paid_charge_rejected
        """
        from test_helpers import get_subscriber
        ctx = create_active_subscription(
            start_date="2026-08-03",
            clock="2026-08-03T00:00:00Z",
            plan_overrides={
                "name": "WO2", "plan_type": "DIGITAL", "issues_per_week": 0,
                "base_weekly_rate_cents": 600,
            },
        )
        charge = list_charges_for_subscription(ctx["subscription"]["id"])[0]
        assert charge["status"] == "OPEN"

        written_off = validate_success(api.write_off_billing_charge(charge["id"], DIRECTOR))
        assert written_off["status"] == "WRITTEN_OFF"

        subscriber = get_subscriber(ctx["subscriber"]["id"])
        assert subscriber["balance_due_cents"] == 0, (
            "written-off charges are excluded from the balance aggregation"
        )


class TestServiceAddressGating:
    def test_service_address_required_for_print(self, api):
        """PRD §3.1: "The address matters: it must be present before any
        print-capable subscription can be created for the account, before a
        plan-change can target a print-capable plan, and before any vacation
        hold, delivery complaint, or route assignment can be attached — its
        absence surfaces as `ERR_SERVICE_ADDRESS_REQUIRED` at those moments."

        Design: Corner/validations/service_address_required_for_print
        """
        plan = create_plan(
            name="SA", plan_type="PRINT", issues_per_week=7,
            base_weekly_rate_cents=600, proration_method="PER_DAY",
            min_weekly_rate_cents=0,
        )
        subscriber = create_subscriber(display_name="SA", email="sa@x.com")

        resp = api.create_subscription(
            {"subscriber_id": subscriber["id"], "plan_id": plan["id"], "start_date": "2026-08-03"},
            REP,
        )
        validate_error(resp, ApiErrorId.ERR_SERVICE_ADDRESS_REQUIRED, 409)

    def test_service_address_not_required_for_digital(self, api):
        """PRD §3.1: "The address matters: it must be present before any
        print-capable subscription can be created for the account, before a
        plan-change can target a print-capable plan, and before any vacation
        hold, delivery complaint, or route assignment can be attached — its
        absence surfaces as `ERR_SERVICE_ADDRESS_REQUIRED` at those moments."
        PRD §3.1: "a count of `issues_per_week` (zero for `DIGITAL` plans,
        between one and seven otherwise)"

        Design: Corner/validations/service_address_required_for_print
        """
        plan = create_plan(
            name="SAD", plan_type="DIGITAL", issues_per_week=0,
            base_weekly_rate_cents=400, proration_method="PER_DAY",
            min_weekly_rate_cents=0,
        )
        subscriber = create_subscriber(display_name="SAD", email="sad@x.com")

        resp = api.create_subscription(
            {"subscriber_id": subscriber["id"], "plan_id": plan["id"], "start_date": "2026-08-03"},
            REP,
        )
        data = validate_success(resp, 201)
        assert data["billing_status"] == "PENDING_START", (
            "digital subscriptions do not require a service address"
        )
