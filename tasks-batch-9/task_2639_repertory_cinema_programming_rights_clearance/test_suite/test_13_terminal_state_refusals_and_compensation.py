"""Terminal-state refusals and the compensation that is owed.

A cancelled screening and a paid order are both done with: no later call may
move them, and none may be allowed to touch the aggregates a second time. Where
a transition genuinely is reversible — a confirmed special event — the reversal
must put back exactly what it took and no more.
"""
from test_helpers import (
    ANONYMOUS,
    BOX_OFFICE,
    PROGRAMMER,
    ApiErrorId,
    api_client,
    assert_order_pricing,
    assert_screen_block,
    assert_seat_conservation,
    assert_special_event,
    cancel_showtime,
    pay_for_order,
    read_booking,
    read_clearance,
    read_order,
    read_showtime,
    sell_seats,
    setup_confirmed_event,
    setup_screening_on_sale,
    setup_scheduled_screening,
    validate_error,
    validate_success,
)


class TestCancelledScreeningIsTerminal:
    """Once a screening is cancelled nothing else may be asked of it."""

    def test_completion_of_a_cancelled_screening_is_refused(self):
        """A cancelled screening cannot be marked played.

        PRD: "State — the addressed resource is in a state from which the requested
        transition is declared, yielding the per-entity invalid-state error. A terminal
        state admits nothing. This covers, among others, an engagement that is neither
        offered nor countered when a counter arrives, a negotiation round that is no
        longer pending when a confirmation arrives, a clearance that is not in the
        submitted state when a clear arrives, a print asset asked to skip a step in the
        traffic chain, a key that is not issued when a revoke arrives, a screening whose
        sale dimension is neither on-sale nor sold-out when an order arrives, a screening
        that is not scheduled when a completion or a cancellation arrives, an order that
        is not reserved when a payment arrives, an order that is not paid when a refund
        arrives, and a settlement that is not a draft when a submission arrives."

        Design: Corner/state_machines/cancelled_showtime_admits_no_further_transition
        """
        world = setup_scheduled_screening("2026-08-14T12:00:00Z")
        showtime_id = world["showtime"]["id"]
        cancelled = cancel_showtime(showtime_id, "WATER_DAMAGE")
        assert cancelled["status"] == "CANCELLED"

        response = api_client.complete_showtime(showtime_id, BOX_OFFICE)
        validate_error(
            response,
            ApiErrorId.ERR_SHOWTIME_INVALID_STATE.value,
            expected_status=409,
        )

        after = read_showtime(showtime_id)
        assert after["status"] == "CANCELLED", "the refused completion moved nothing"
        assert after["cancel_reason"] == "WATER_DAMAGE"
        assert after["sale_status"] == "SALES_CLOSED", (
            "cancellation forced the sale dimension closed and it stays closed"
        )
        assert after["gross_cents"] == 0

    def test_second_cancellation_of_a_cancelled_screening_is_refused(self):
        """Cancelling twice cannot return the licence allowance twice.

        PRD: "State — the addressed resource is in a state from which the requested
        transition is declared, yielding the per-entity invalid-state error. A terminal
        state admits nothing. This covers, among others, an engagement that is neither
        offered nor countered when a counter arrives, a negotiation round that is no
        longer pending when a confirmation arrives, a clearance that is not in the
        submitted state when a clear arrives, a print asset asked to skip a step in the
        traffic chain, a key that is not issued when a revoke arrives, a screening whose
        sale dimension is neither on-sale nor sold-out when an order arrives, a screening
        that is not scheduled when a completion or a cancellation arrives, an order that
        is not reserved when a payment arrives, an order that is not paid when a refund
        arrives, and a settlement that is not a draft when a submission arrives."

        PRD: "The licence gets its allowance back — `screenings_used` falls by one,
        `screenings_remaining` rises by one, and the licence's `version` increments — and
        the engagement's `scheduled_showtime_count` falls by one."

        Design: Corner/state_machines/cancelled_showtime_admits_no_further_transition
        """
        world = setup_scheduled_screening("2026-08-14T12:00:00Z")
        showtime_id = world["showtime"]["id"]
        cancel_showtime(showtime_id, "WATER_DAMAGE")

        response = api_client.cancel_showtime(
            showtime_id, {"cancel_reason": "SECOND_ATTEMPT"}, PROGRAMMER
        )
        validate_error(
            response,
            ApiErrorId.ERR_SHOWTIME_INVALID_STATE.value,
            expected_status=409,
        )

        after = read_showtime(showtime_id)
        assert after["cancel_reason"] == "WATER_DAMAGE", (
            "the refused second cancellation did not overwrite the stored reason"
        )

        clearance = read_clearance(world["clearance"]["id"])
        assert clearance["screenings_used"] == 0, (
            "the allowance came back exactly once"
        )
        assert clearance["screenings_remaining"] == 6

        booking = read_booking(world["booking"]["id"])
        assert booking["scheduled_showtime_count"] == 0, (
            "the engagement's scheduled count fell exactly once"
        )


class TestPaidOrderIsTerminalForPayment:
    """Payment happens once, and the box-office rollup records it once."""

    def test_paying_an_already_paid_order_is_refused(self):
        """A second payment on the same order is an invalid-state refusal.

        PRD: "An order that is not `RESERVED` when payment arrives, or not `PAID` when a
        refund arrives, yields `ERR_TICKET_ORDER_INVALID_STATE`."

        Design: Corner/state_machines/paying_an_already_paid_ticket_order_returns_invalid_state
        """
        world = setup_screening_on_sale("2026-08-14T12:00:00Z")
        order = sell_seats(world["showtime"]["id"], 2, headers=ANONYMOUS)
        paid = pay_for_order(order["id"])
        assert paid["status"] == "PAID"
        assert_order_pricing(
            paid,
            unit_price_cents=1450,
            line_subtotal_cents=2900,
            facility_fee_cents=300,
            total_cents=3200,
        )

        response = api_client.pay_ticket_order(order["id"], BOX_OFFICE)
        validate_error(
            response,
            ApiErrorId.ERR_TICKET_ORDER_INVALID_STATE.value,
            expected_status=409,
        )

        after = read_order(order["id"])
        assert after["status"] == "PAID", "the order is still simply paid"
        assert after["total_cents"] == 3200, "the pinned price is untouched"

    def test_repeat_payment_does_not_double_count_the_box_office_rollup(self):
        """The screening's gross and admissions count the paid order exactly once.

        PRD: "Paying an order moves it `RESERVED → PAID`, which requires the screening
        still to be `SCHEDULED`, and adds the order's `total_cents` to the screening's
        `gross_cents` and its `quantity` to the screening's `admissions_count`; only paid
        orders ever count towards gross."

        PRD: "An order that is not `RESERVED` when payment arrives, or not `PAID` when a
        refund arrives, yields `ERR_TICKET_ORDER_INVALID_STATE`."

        Design: Corner/state_machines/paying_an_already_paid_ticket_order_returns_invalid_state
        """
        world = setup_screening_on_sale("2026-08-14T12:00:00Z")
        order = sell_seats(world["showtime"]["id"], 2, headers=ANONYMOUS)
        pay_for_order(order["id"])

        response = api_client.pay_ticket_order(order["id"], BOX_OFFICE)
        validate_error(
            response,
            ApiErrorId.ERR_TICKET_ORDER_INVALID_STATE.value,
            expected_status=409,
        )

        showtime = read_showtime(world["showtime"]["id"])
        assert showtime["gross_cents"] == 3200, (
            "the 3200-cent order is counted once, not twice"
        )
        assert showtime["admissions_count"] == 2, "two admissions, not four"
        assert showtime["seats_sold"] == 2
        assert showtime["seats_available"] == 6
        assert_seat_conservation(showtime, world["venue"])


class TestSpecialEventCompensation:
    """Cancelling a confirmed event gives the screen back, and nothing else."""

    def test_cancelling_a_confirmed_event_restores_the_screen_block(self):
        """The screening's extension and surcharge are reversed exactly.

        PRD: "Cancelling a `CONFIRMED` event compensates: the screening's `extra_minutes`
        and `surcharge_cents` both return to 0 and `end_at` and `blocked_until` are
        recomputed back to their pre-confirmation values, freeing the screen again."

        PRD: "Screenings already displaced are not resurrected — the calendar has moved
        on, the audience has been told, and `displaced_showtime_ids` is retained as the
        audit trail of what the production cost."

        Design: Corner/state_machines/special_event_cancel_after_confirm_restores_the_showtime_block
        """
        world = setup_confirmed_event(
            "2026-08-14T12:00:00Z",
            displace_conflicts=False,
            event_overrides={
                "event_type": "FILMMAKER_QA",
                "guest_name": "Agnes Roux",
                "extra_minutes": 30,
                "surcharge_cents": 500,
                "guest_fee_cents": 40000,
            },
        )
        confirmed_showtime = world["showtime"]
        assert world["event"]["status"] == "CONFIRMED"
        assert confirmed_showtime["extra_minutes"] == 30
        assert confirmed_showtime["surcharge_cents"] == 500
        assert_screen_block(
            confirmed_showtime, "2026-08-14T14:26:00.000Z", "2026-08-14T14:51:00.000Z"
        )

        response = api_client.cancel_special_event(
            world["event"]["id"],
            {"cancel_reason": "Guest cancelled after confirmation"},
            PROGRAMMER,
        )
        event = validate_success(response, expected_status=200)

        assert event["status"] == "CANCELLED"
        assert event["displaced_showtime_ids"] == [], (
            "nothing was displaced, and the audit trail is retained as it stood"
        )
        assert_special_event(event)

        showtime = read_showtime(confirmed_showtime["id"])
        assert showtime["extra_minutes"] == 0, "the extension is reversed"
        assert showtime["surcharge_cents"] == 0, "the surcharge is reversed"
        assert_screen_block(
            showtime, "2026-08-14T13:56:00.000Z", "2026-08-14T14:21:00.000Z"
        )
        assert showtime["status"] == "SCHEDULED", (
            "the screening itself is untouched by the event's cancellation"
        )
        assert showtime["sale_status"] == "DRAFT"

        clearance = read_clearance(world["clearance"]["id"])
        assert clearance["screenings_used"] == 1, (
            "the screening still stands, so its draw-down still stands"
        )
        assert clearance["screenings_remaining"] == 5
