"""Weather events, cancellation cascades, and guest credits: provisional vs
final variants, notice tiers, hold cycles, and settlement (PRD §3.8)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assign_confirmed_bartender,
    cancel_booking,
    create_booking,
    create_cruise,
    create_customer,
    create_paid_booking,
    create_parking_pass,
    create_placed_provision_order,
    declare_weather_event,
    get_booking,
    get_cruise,
    set_clock,
    settle_credits,
    setup_inventory,
    setup_weather_cancelled_cruise,
    validate_error,
    validate_success,
    weather_cancel,
)

OM = TEST_USERS["ops_manager_headers"]
CAPTAIN = TEST_USERS["captain_headers"]
ATTENDANT = TEST_USERS["dock_attendant_headers"]


class TestWeatherCreditProvisionalVsFinal:
    def _setup_cancelled_with_placed_order(self, api):
        """Party-4 holiday PEAK booking (total 48275), order PLACED with 4
        covers, cancelled at 30h notice (75% tier). Returns context."""
        inv = setup_inventory()
        cruise = create_cruise(inv["vessel"]["id"], inv["tier"]["id"],
                               depart_at="2026-07-04T19:00:00Z",
                               return_at="2026-07-04T22:00:00Z")
        customer = create_customer("ana@example.com", "Ana")
        booking = create_paid_booking(cruise["id"], customer["id"], 4,
                                      cruise["version"])
        order = create_placed_provision_order(cruise["id"])
        set_clock("2026-07-03T13:00:00Z")
        event = declare_weather_event(
            window_start="2026-07-04T00:00:00Z",
            window_end="2026-07-05T00:00:00Z")
        weather_cancel(cruise["id"])
        return {**inv, "cruise": cruise, "customer": customer,
                "booking": booking, "order": order, "event": event}

    def test_provisional_and_final_variants_diverge(self, api):
        """PRD §3.8: "the provisional amount is the booking's frozen
        `booking_total_cents` multiplied by that percentage, rounded half-up to
        whole cents."
        PRD §3.8: "when the cruise's provision order stood at `PLACED` at
        cancellation time, the restocking rebate of 300 cents per
        `provisional_covers` is added; and a flat processing fee of 450 cents is
        subtracted, yielding the credit's `final_amount_cents`."
        PRD §3.8: "A customer's `credit_balance_cents` is the sum over their
        credits of the `amount_cents` while a credit stands at `ISSUED`, the
        `final_amount_cents` while it stands at `SETTLED`, and zero once it
        stands at `REDEEMED` or `EXPIRED`."

        Design: Difficulty/dual_variant_calc/weather_credit_provisional_vs_final_diverge
        """
        ctx = self._setup_cancelled_with_placed_order(api)
        booking_id = ctx["booking"]["id"]

        credits = validate_success(api.list_booking_credits(booking_id, OM))
        assert len(credits) == 1
        credit = credits[0]
        # Provisional: round_half_up(48275 * 0.75) = 36206 (no rebate, no fee).
        assert credit["credit_status"] == "ISSUED"
        assert credit["amount_cents"] == 36206, (
            f"Provisional credit must be 36206 (75% of 48275), got "
            f"{credit['amount_cents']}"
        )

        settle_credits(ctx["event"]["id"])
        settled = validate_success(api.get_credit(credit["id"], OM))
        # Final: 36206 + 4*300 rebate - 450 fee = 36956.
        assert settled["credit_status"] == "SETTLED"
        assert settled["final_amount_cents"] == 36956, (
            f"Final credit must be 36956 (36206 + 1200 rebate - 450 fee), got "
            f"{settled['final_amount_cents']}"
        )
        customer = validate_success(api.get_customer(ctx["customer"]["id"], OM))
        assert customer["credit_balance_cents"] == 36956, (
            f"SETTLED credits count at final_amount_cents, got "
            f"{customer['credit_balance_cents']}"
        )

    def test_provisional_issued_before_settlement_at_amount_cents(self, api):
        """PRD §3.8: "For each such booking a **CruiseCredit** is created in
        `ISSUED` status with a provisional `amount_cents`"
        PRD §3.8: "at least twenty-four but fewer than seventy-two yields
        seventy-five percent"

        Design: Difficulty/dual_variant_calc/weather_credit_provisional_vs_final_diverge
        """
        ctx = self._setup_cancelled_with_placed_order(api)
        customer = validate_success(api.get_customer(ctx["customer"]["id"], OM))
        # While ISSUED, the balance reads the provisional amount.
        assert customer["credit_balance_cents"] == 36206
        credits = validate_success(api.list_booking_credits(
            ctx["booking"]["id"], OM))
        assert credits[0]["amount_cents"] == 36206
        assert credits[0]["credit_status"] == "ISSUED"


class TestWeatherCancelCascadeDepth4:
    def test_full_cascade_from_single_weather_cancel(self, api):
        """PRD §3.8: "The cancellation then executes a six-part cascade,
        atomically:"
        PRD §3.8: "Every booking of the cruise whose `payment_status` is
        `PENDING` or `PAID` moves to `REFUND_PENDING`, and its `booking_status`
        moves to `CANCELLED`."
        PRD §3.8: "The driving weather event moves from `DECLARED` to
        `CANCELLATION_ISSUED` — this happens on the first weather-cancel beneath
        it."
        PRD §3.8: "Every parking pass for the cruise standing at `RESERVED` moves
        to `RELEASED`, decrementing the dock's `parking_in_use` once per released
        pass."
        PRD §3.8: "Every staff assignment for the cruise standing at `ASSIGNED`
        or `CONFIRMED` moves to `RELEASED`, with `bar_service_enabled`
        recomputed."
        PRD §3.8: "The cruise's provision order, if standing at `DRAFT` or
        `PLACED`, moves to `CANCELLED`; if it stood at `PLACED`, its
        `restocking_rebate_cents` is computed as 300 cents per provisional cover
        (§3.5)."

        Design: Difficulty/transitive_cascade/weather_cancel_cascade_depth4
        """
        inv = setup_inventory()
        cruise = inv["cruise"]
        customer = create_customer("a@example.com", "A")
        booking = create_paid_booking(cruise["id"], customer["id"], 2,
                                      cruise["version"])
        order = create_placed_provision_order(cruise["id"])
        assignment = assign_confirmed_bartender(cruise["id"])
        parking_pass = create_parking_pass(inv["dock"]["id"], booking["id"],
                                           cruise["id"])
        dock_before = validate_success(api.get_dock(inv["dock"]["id"], OM))
        assert dock_before["parking_in_use"] == 1

        set_clock("2026-08-09T13:00:00Z")
        event = declare_weather_event()
        cancelled = weather_cancel(cruise["id"])

        # Hop 0: the cruise itself.
        assert cancelled["status"] == "CANCELLED"
        # Hop 2: booking payment axis.
        booking_after = get_booking(booking["id"])
        assert booking_after["payment_status"] == "REFUND_PENDING"
        assert booking_after["booking_status"] == "CANCELLED"
        # Hop 3: provisional credit (75% of 22250 = 16688).
        credits = validate_success(api.list_booking_credits(booking["id"], OM))
        assert len(credits) == 1
        assert credits[0]["credit_status"] == "ISSUED"
        assert credits[0]["amount_cents"] == 16688, (
            f"Provisional credit must be 16688 (75% of 22250), got "
            f"{credits[0]['amount_cents']}"
        )
        # Event driven by the cancellation.
        event_after = validate_success(api.get_weather_event(event["id"], OM))
        assert event_after["status"] == "CANCELLATION_ISSUED"
        # Hop 4: parking pass released, dock aggregate decremented.
        pass_after = validate_success(api.get_parking_pass(parking_pass["id"],
                                                           OM))
        assert pass_after["status"] == "RELEASED"
        dock_after = validate_success(api.get_dock(inv["dock"]["id"], OM))
        assert dock_after["parking_in_use"] == 0
        # Provision order cancelled with the restocking rebate (2 covers * 300).
        orders = validate_success(api.list_provision_orders(
            cruise["id"], TEST_USERS["galley_manager_headers"]))
        order_after = next(o for o in orders if o["id"] == order["id"])
        assert order_after["status"] == "CANCELLED"
        assert order_after["restocking_rebate_cents"] == 600, (
            f"Rebate must be 600 (2 covers * 300), got "
            f"{order_after['restocking_rebate_cents']}"
        )
        # Staff assignment released.
        assignments = validate_success(api.list_staff_assignments(
            cruise["id"], OM))
        assignment_after = next(a for a in assignments
                                if a["id"] == assignment["id"])
        assert assignment_after["status"] == "RELEASED"

    def test_customer_cancelled_booking_untouched_by_cascade(self, api):
        """PRD §3.8: "Bookings already cancelled by their customers are
        untouched by the cascade."

        Design: Difficulty/transitive_cascade/weather_cancel_cascade_depth4
        """
        inv = setup_inventory()
        cruise = inv["cruise"]
        customer = create_customer("a@example.com", "A")
        booking = create_booking(cruise["id"], customer["id"], 1,
                                 cruise["version"])
        cancel_booking(booking["id"], customer["id"])
        set_clock("2026-08-09T13:00:00Z")
        declare_weather_event()
        weather_cancel(cruise["id"])

        booking_after = get_booking(booking["id"])
        assert booking_after["booking_status"] == "CANCELLED"
        assert booking_after["payment_status"] == "PENDING", (
            "A customer-cancelled unpaid booking must not be moved to "
            "REFUND_PENDING by the cascade"
        )
        credits = validate_success(api.list_booking_credits(booking["id"], OM))
        assert credits == [], (
            "No credit is issued for a booking already cancelled by its customer"
        )


class TestWeatherCreditNoticeTiers:
    def test_seventy_two_hour_and_five_hour_boundaries(self, api):
        """PRD §3.8: "the number of whole hours between the current logical
        clock reading and the cruise's scheduled `depart_at` selects a
        percentage — at least seventy-two hours of notice yields one hundred
        percent; at least twenty-four but fewer than seventy-two yields
        seventy-five percent; at least six but fewer than twenty-four yields
        fifty percent; fewer than six hours yields twenty-five percent"

        Design: Corner/calculations/weather_credit_notice_tier_boundaries
        """
        inv = setup_inventory()
        vessel = inv["vessel"]
        tier = inv["tier"]
        cr_x = create_cruise(vessel["id"], tier["id"])
        cr_y = create_cruise(vessel["id"], tier["id"])
        customer = create_customer("a@example.com", "A")
        bk_x = create_paid_booking(cr_x["id"], customer["id"], 2,
                                   cr_x["version"])
        bk_y = create_paid_booking(cr_y["id"], customer["id"], 2,
                                   cr_y["version"])

        # Cruise X cancelled at exactly 72 hours of notice -> 100%.
        set_clock("2026-08-07T19:00:00Z")
        declare_weather_event()
        weather_cancel(cr_x["id"])
        # Cruise Y cancelled at 5 hours of notice -> 25%.
        set_clock("2026-08-10T14:00:00Z")
        weather_cancel(cr_y["id"])

        credit_x = validate_success(api.list_booking_credits(bk_x["id"], OM))[0]
        credit_y = validate_success(api.list_booking_credits(bk_y["id"], OM))[0]
        # PEAK non-holiday party 2: round_half_up(17800*1.25) = 22250.
        assert credit_x["amount_cents"] == 22250, (
            f"72h notice must credit 100% (22250), got {credit_x['amount_cents']}"
        )
        # round_half_up(22250 * 0.25) = 5563.
        assert credit_y["amount_cents"] == 5563, (
            f"5h notice must credit 25% (5563), got {credit_y['amount_cents']}"
        )
        assert get_booking(bk_x["id"])["payment_status"] == "REFUND_PENDING"
        assert get_booking(bk_y["id"])["payment_status"] == "REFUND_PENDING"


class TestWeatherEventLifecycle:
    def test_weather_cancel_without_covering_event_rejected(self, api):
        """PRD §3.8: "The cruise must stand at `SCHEDULED` or `WEATHER_HOLD`
        (otherwise `ERR_INVALID_STATE`), and there must exist a covering
        `CANCELLATION_REQUIRED` event standing at `DECLARED` or
        `CANCELLATION_ISSUED` (otherwise `ERR_NO_ACTIVE_WEATHER_EVENT`)."

        Design: Corner/validations/weather_cancel_without_event_rejected
        """
        inv = setup_inventory()
        resp = api.weather_cancel_cruise(inv["cruise"]["id"], OM)
        validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_WEATHER_EVENT)

    def test_settle_credits_twice_rejected(self, api):
        """PRD §3.8: "An `OperationsManager` settles credits for an event that
        stands at `CANCELLATION_ISSUED` (otherwise `ERR_INVALID_STATE`)"
        PRD §3.8: "the event itself advances from `CANCELLATION_ISSUED` to
        `CREDITS_SETTLED`, which is terminal."

        Design: Corner/validations/settle_credits_twice_rejected
        """
        ctx = setup_weather_cancelled_cruise(clock_at="2026-08-09T13:00:00Z",
                                             party_size=2)
        settle_credits(ctx["event"]["id"])
        resp = api.settle_weather_event_credits(ctx["event"]["id"], OM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_close_event_with_outstanding_hold_rejected(self, api):
        """PRD §3.8: "moving it from `DECLARED` to `CLOSED` requires the
        `DECLARED` state (otherwise `ERR_INVALID_STATE`) and requires that no
        covered cruise remain in `WEATHER_HOLD` (otherwise
        `ERR_WEATHER_HOLDS_OUTSTANDING`)."
        PRD §3.8: "When the severity is `CANCELLATION_REQUIRED`, declaration
        immediately places every still-`SCHEDULED` cruise whose scheduled
        departure instant falls inside the window into `WEATHER_HOLD`"

        Design: Corner/validations/close_event_with_outstanding_hold_rejected
        """
        inv = setup_inventory()
        event = declare_weather_event()
        assert get_cruise(inv["cruise"]["id"])["status"] == "WEATHER_HOLD"
        resp = api.close_weather_event(event["id"], OM)
        validate_error(resp, ApiErrorId.ERR_WEATHER_HOLDS_OUTSTANDING)

    def test_clear_hold_blocked_once_cancellation_issued(self, api):
        """PRD §3.8: "Clearing a weather hold moves the cruise from
        `WEATHER_HOLD` back to `SCHEDULED` and is permitted while the covering
        event stands at `DECLARED` or `CLOSED` — an operator may elect to sail
        despite a declared event — but once the covering event has advanced to
        `CANCELLATION_ISSUED`, clearing is rejected with
        `ERR_WEATHER_EVENT_ACTIVE`."

        Design: Corner/validations/clear_hold_while_event_active_rejected
        """
        inv = setup_inventory()
        cr_a = inv["cruise"]
        cr_b = create_cruise(inv["vessel"]["id"], inv["tier"]["id"],
                             depart_at="2026-08-10T20:00:00Z",
                             return_at="2026-08-10T23:00:00Z")
        event = declare_weather_event()
        # Both cruises auto-held; cancelling A advances the event.
        assert get_cruise(cr_b["id"])["status"] == "WEATHER_HOLD"
        weather_cancel(cr_a["id"])
        assert validate_success(api.get_weather_event(event["id"], OM))[
            "status"] == "CANCELLATION_ISSUED"

        resp = api.clear_weather_hold(cr_b["id"], OM)
        validate_error(resp, ApiErrorId.ERR_WEATHER_EVENT_ACTIVE)

    def test_weather_hold_cycle_repeats_across_events(self, api):
        """PRD §3.8: "The `SCHEDULED` → `WEATHER_HOLD` → `SCHEDULED` cycle may
        repeat across distinct weather events."
        PRD §3.8: "Clearing a weather hold moves the cruise from `WEATHER_HOLD`
        back to `SCHEDULED` and is permitted while the covering event stands at
        `DECLARED` or `CLOSED`"

        Design: Corner/state_machines/weather_hold_cycle_repeated
        """
        inv = setup_inventory()
        cruise_id = inv["cruise"]["id"]
        event1 = declare_weather_event()
        assert get_cruise(cruise_id)["status"] == "WEATHER_HOLD"
        cleared = validate_success(api.clear_weather_hold(cruise_id, OM))
        assert cleared["status"] == "SCHEDULED"
        closed = validate_success(api.close_weather_event(event1["id"], OM))
        assert closed["status"] == "CLOSED"

        declare_weather_event()
        assert get_cruise(cruise_id)["status"] == "WEATHER_HOLD", (
            "A second CANCELLATION_REQUIRED event must re-hold the same cruise"
        )


class TestSettleCreditsSatisfaction:
    def test_settle_succeeds_when_all_bookings_refund_pending(self, api):
        """PRD §3.8: "An `OperationsManager` settles credits for an event that
        stands at `CANCELLATION_ISSUED` (otherwise `ERR_INVALID_STATE`), and only
        when every booking on every cruise cancelled under the event still stands
        at `REFUND_PENDING` — if any such booking has moved on, settlement is
        rejected with `ERR_CREDITS_NOT_PENDING`."
        PRD §3.8: "The credit moves from `ISSUED` to `SETTLED`, the booking's
        `payment_status` moves from `REFUND_PENDING` to `CREDITED`, each affected
        customer's `credit_balance_cents` is recomputed, and the event itself
        advances from `CANCELLATION_ISSUED` to `CREDITS_SETTLED`, which is
        terminal."

        Design: Corner/errors/error_credits_not_pending_not_triggerable_after_cancel
        """
        ctx = setup_weather_cancelled_cruise(clock_at="2026-08-09T13:00:00Z",
                                             party_size=1)
        settled_event = settle_credits(ctx["event"]["id"])
        assert settled_event["status"] == "CREDITS_SETTLED"
        assert get_booking(ctx["booking"]["id"])["payment_status"] == "CREDITED"
