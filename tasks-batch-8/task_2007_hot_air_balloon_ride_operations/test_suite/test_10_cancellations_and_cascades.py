"""Flight cancellation cascades (weather, operator, aircraft), the NO_GO
reschedule loop, terminal-state lockdown, and operator goodwill (PRD §3.6,
§3.7)."""
from test_helpers import (
    ApiErrorId,
    approve_refund,
    assert_reservation,
    book_reservation,
    cancel_flight,
    create_confirmed_booking,
    create_draft_flight,
    enter_weather_review,
    get_flight,
    get_customer,
    get_reservation,
    get_success_data,
    list_refunds,
    pay_refund,
    record_no_go,
    setup_scheduled_flight,
    sole_refund,
    validate_error,
    validate_success,
)


class TestTerminalLockdown:
    def test_flight_terminal_cancelled_lockdown(self, api, ops_headers):
        """PRD §3.6: "`CLOSED` is terminal, as is `CANCELLED`."
        PRD §2.9: "From-state validity: the resource is in a state from which
        the requested transition exists (`ERR_INVALID_STATE`, HTTP 409)."

        Design: Corner/state_machines/flight_terminal_cancelled_lockdown
        """
        ctx = setup_scheduled_flight()
        cancel_flight(ctx)
        assert ctx["flight"]["status"] == "CANCELLED"
        resp = api.flight_event(
            ctx["flight"]["id"],
            {
                "event_type": "RESCHEDULE",
                "new_scheduled_date": "2026-08-11",
                "new_dawn_window_start": "2026-08-11T05:30:00Z",
                "new_dawn_window_end": "2026-08-11T07:00:00Z",
            },
            ops_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_flight(ctx["flight"]["id"])["status"] == "CANCELLED"


class TestNoGoRescheduleLoop:
    def test_no_go_reschedule_restores_scheduled_with_reset(self, api, ops_headers):
        """PRD §3.7: "Rescheduling — an `OperationsManager` action carrying
        `new_scheduled_date`, `new_dawn_window_start`, and
        `new_dawn_window_end` — returns the flight to `SCHEDULED`."
        PRD §3.7: "The new window must again be exactly ninety minutes, the
        balloon and pilot must be free under the same overlap rules that govern
        publishing (`ERR_BALLOON_SCHEDULE_CONFLICT`,
        `ERR_PILOT_SCHEDULE_CONFLICT`), and on success the flight's
        `scheduled_date` and dawn window are replaced, `season_tier` is
        recomputed from the new date, and `weather_decision` /
        `weather_decision_at` reset to `NONE` and null."
        PRD §3.7: "Attached reservations keep their `booking_status` and their
        `paid_cents`; rescheduling never auto-refunds."

        Design: Difficulty/non_linear_state_machine/flight_no_go_reschedule_cycle
        """
        ctx = setup_scheduled_flight()
        customer, reservation = create_confirmed_booking(
            ctx["flight"], party_size=1, declared_weight_lbs=180
        )
        enter_weather_review(ctx)
        record_no_go(ctx)
        assert ctx["flight"]["status"] == "NO_GO"
        assert ctx["flight"]["weather_decision"] == "NO_GO"

        resp = api.flight_event(
            ctx["flight"]["id"],
            {
                "event_type": "RESCHEDULE",
                "new_scheduled_date": "2026-08-11",
                "new_dawn_window_start": "2026-08-11T05:30:00Z",
                "new_dawn_window_end": "2026-08-11T07:00:00Z",
            },
            ops_headers,
        )
        flight = validate_success(resp)
        assert flight["status"] == "SCHEDULED"
        assert flight["scheduled_date"] == "2026-08-11"
        assert flight["dawn_window_start"] == "2026-08-11T05:30:00Z"
        assert flight["dawn_window_end"] == "2026-08-11T07:00:00Z"
        assert flight["weather_decision"] == "NONE", "reschedule resets the go/no-go decision"
        assert flight["weather_decision_at"] is None

        intact = get_reservation(reservation["id"])
        assert intact["booking_status"] == "CONFIRMED", "reservations ride along on reschedule"
        assert intact["paid_cents"] == 29900
        assert list_refunds(reservation["id"]) == [], "rescheduling never auto-refunds"

    def test_no_go_reschedule_recomputes_season_tier(self, api, ops_headers):
        """PRD §3.7: "on success the flight's `scheduled_date` and dawn window
        are replaced, `season_tier` is recomputed from the new date".
        PRD §3.2: "`PEAK` when `scheduled_date` falls within October 1 through
        October 14 — the Balloon Fiesta window — and `REGULAR` otherwise."

        Design: Difficulty/non_linear_state_machine/flight_no_go_reschedule_cycle
        """
        ctx = setup_scheduled_flight()
        assert ctx["flight"]["season_tier"] == "REGULAR"  # 2026-08-10
        enter_weather_review(ctx)
        record_no_go(ctx)

        resp = api.flight_event(
            ctx["flight"]["id"],
            {
                "event_type": "RESCHEDULE",
                "new_scheduled_date": "2026-10-05",
                "new_dawn_window_start": "2026-10-05T05:30:00Z",
                "new_dawn_window_end": "2026-10-05T07:00:00Z",
            },
            ops_headers,
        )
        flight = validate_success(resp)
        assert flight["status"] == "SCHEDULED"
        assert flight["scheduled_date"] == "2026-10-05"
        assert flight["season_tier"] == "PEAK", (
            "season_tier is recomputed from the new date"
        )


class TestWeatherCancelCascade:
    def test_weather_cancel_cascades_reservations_and_refunds(self, api, ops_headers):
        """PRD §3.7: "Cancelling an `NO_GO` flight sets the flight's
        `cancel_reason` to `WEATHER`. Every reservation in `PENDING`,
        `CONFIRMED`, or `CHECKED_IN` cascades to `CANCELLED` with its own
        `cancel_reason` of `WEATHER_CANCEL`, and for each such reservation whose
        `payment_status` is `PAID`, a `Refund` is auto-created in `REQUESTED`
        with its `reason` set to `WEATHER_CANCEL` and a policy-computed
        `requested_amount_cents`."
        PRD §3.7: "On a `SHARED` flight, a 100-percent policy triggers the
        full-fare carve-out: the requested amount is simply `paid_cents`,
        exactly."

        Design: Difficulty/transitive_cascade/weather_no_go_cancel_cascade
        """
        ctx = setup_scheduled_flight()
        _, r1 = create_confirmed_booking(ctx["flight"], party_size=1, declared_weight_lbs=180)
        _, r2 = create_confirmed_booking(ctx["flight"], party_size=2, declared_weight_lbs=360)
        assert r1["paid_cents"] == 29900
        assert r2["paid_cents"] == 59800
        enter_weather_review(ctx)
        record_no_go(ctx)
        cancel_flight(ctx)

        flight = get_flight(ctx["flight"]["id"])
        assert flight["status"] == "CANCELLED"
        assert flight["cancel_reason"] == "WEATHER"

        for reservation, expected in ((r1, 29900), (r2, 59800)):
            after = get_reservation(reservation["id"])
            assert_reservation(after)
            assert after["booking_status"] == "CANCELLED"
            assert after["cancel_reason"] == "WEATHER_CANCEL"
            refund = sole_refund(reservation["id"])
            assert refund["status"] == "REQUESTED"
            assert refund["reason"] == "WEATHER_CANCEL"
            assert refund["requested_amount_cents"] == expected, (
                f"full-fare carve-out: requested == paid_cents {expected}"
            )

    def test_weather_cancel_skips_refund_for_unpaid_reservation(self, api, ops_headers):
        """PRD §3.7: "Every reservation in `PENDING`, `CONFIRMED`, or
        `CHECKED_IN` cascades to `CANCELLED` with its own `cancel_reason` of
        `WEATHER_CANCEL`, and for each such reservation whose `payment_status`
        is `PAID`, a `Refund` is auto-created in `REQUESTED`" — an unpaid
        reservation is cancelled without any refund.

        Design: Difficulty/transitive_cascade/weather_no_go_cancel_cascade
        """
        ctx = setup_scheduled_flight()
        _, r_paid = create_confirmed_booking(
            ctx["flight"], party_size=1, declared_weight_lbs=180
        )
        _, r_unpaid = book_reservation(ctx["flight"], party_size=1, declared_weight_lbs=180)
        enter_weather_review(ctx)
        record_no_go(ctx)
        cancel_flight(ctx)

        unpaid_after = get_reservation(r_unpaid["id"])
        assert unpaid_after["booking_status"] == "CANCELLED"
        assert unpaid_after["cancel_reason"] == "WEATHER_CANCEL"
        assert unpaid_after["payment_status"] == "UNPAID"
        assert list_refunds(r_unpaid["id"]) == [], (
            "no refund is auto-created for a reservation that never paid"
        )
        assert len(list_refunds(r_paid["id"])) == 1


class TestBalloonGroundCascade:
    def test_balloon_ground_cascades_with_goodwill(self, api, ops_headers):
        """PRD §3.7: "Grounding a balloon is itself an operator-level cancel:
        every `SCHEDULED` flight using that balloon cascades to `CANCELLED` with
        `cancel_reason` `AIRCRAFT`, those flights' reservations in `PENDING`,
        `CONFIRMED`, or `CHECKED_IN` cascade to `CANCELLED` with reason
        `OPERATOR_CANCEL`, refunds are auto-created for the paid ones, and the
        same ten-percent goodwill credit applies."
        PRD §3.7 (operator cancel): "each refunded reservation's
        `goodwill_credit_cents` is set to ten percent of its `paid_cents`,
        rounded half-up to the nearest cent."

        Design: Difficulty/transitive_cascade/balloon_ground_cascade
        """
        ctx = setup_scheduled_flight()
        _, reservation = create_confirmed_booking(
            ctx["flight"], party_size=1, declared_weight_lbs=180
        )
        assert reservation["paid_cents"] == 29900

        grounded = get_success_data(
            api.balloon_event(ctx["balloon"]["id"], {"event_type": "GROUND"}, ops_headers)
        )
        assert grounded["status"] == "GROUNDED"

        flight = get_flight(ctx["flight"]["id"])
        assert flight["status"] == "CANCELLED"
        assert flight["cancel_reason"] == "AIRCRAFT"

        after = get_reservation(reservation["id"])
        assert after["booking_status"] == "CANCELLED"
        assert after["cancel_reason"] == "OPERATOR_CANCEL"
        assert after["goodwill_credit_cents"] == 2990, "round_half_up(29900 * 0.10)"

        refund = sole_refund(reservation["id"])
        assert refund["status"] == "REQUESTED"
        assert refund["reason"] == "OPERATOR_CANCEL"
        assert refund["requested_amount_cents"] == 29900

    def test_balloon_ground_goodwill_credited_on_refund_pay(self, api, ops_headers):
        """PRD §3.7: "Independently of the payment channel, paying a refund
        whose reason is `OPERATOR_CANCEL` additionally credits the reservation's
        `goodwill_credit_cents` to the customer's wallet."

        Design: Difficulty/transitive_cascade/balloon_ground_cascade
        """
        ctx = setup_scheduled_flight()
        customer, reservation = create_confirmed_booking(
            ctx["flight"], party_size=1, declared_weight_lbs=180
        )
        get_success_data(
            api.balloon_event(ctx["balloon"]["id"], {"event_type": "GROUND"}, ops_headers)
        )
        refund = sole_refund(reservation["id"])
        approve_refund(refund["id"], 29900)
        pay_refund(refund["id"], "ORIGINAL_PAYMENT")

        after = get_reservation(reservation["id"])
        assert after["refunded_cents"] == 29900
        assert after["payment_status"] == "REFUNDED"
        # 2990 goodwill lands in the wallet even though the refund itself was
        # paid back through the original payment channel.
        assert get_customer(customer["id"])["wallet_credit_cents"] == 2990

    def test_balloon_ground_leaves_draft_flights_untouched(self, api, ops_headers):
        """PRD §3.7: "Grounding a balloon is itself an operator-level cancel:
        every `SCHEDULED` flight using that balloon cascades to `CANCELLED` with
        `cancel_reason` `AIRCRAFT`, those flights' reservations in `PENDING`,
        `CONFIRMED`, or `CHECKED_IN` cascade to `CANCELLED` with reason
        `OPERATOR_CANCEL`, refunds are auto-created for the paid ones, and the
        same ten-percent goodwill credit applies." — a flight still in `DRAFT`
        is not part of the cascade.

        Design: Difficulty/transitive_cascade/balloon_ground_cascade
        """
        ctx = setup_scheduled_flight()
        draft = create_draft_flight(
            ctx,
            scheduled_date="2026-08-12",
            dawn_window_start="2026-08-12T05:30:00Z",
            dawn_window_end="2026-08-12T07:00:00Z",
        )
        get_success_data(
            api.balloon_event(ctx["balloon"]["id"], {"event_type": "GROUND"}, ops_headers)
        )
        assert get_flight(ctx["flight"]["id"])["status"] == "CANCELLED"
        draft_after = get_flight(draft["id"])
        assert draft_after["status"] == "DRAFT", (
            "the aircraft cascade reaches SCHEDULED flights only"
        )
        assert draft_after["cancel_reason"] is None
