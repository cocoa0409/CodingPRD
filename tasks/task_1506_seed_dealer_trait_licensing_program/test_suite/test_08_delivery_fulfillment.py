"""Delivery scheduling rules (window, capacity, remainder), completion timing,
and the order's parallel payment/fulfillment dimensions."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_line,
    complete_ticket,
    confirm_order,
    create_draft_order,
    schedule_delivery,
    set_clock,
    setup_confirmed_order,
    setup_delivered_order,
    setup_market,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
SALESREP = TEST_USERS["salesrep_headers"]


class TestDeliverySchedulingRules:
    def test_delivery_scheduled_outside_window_rejected(self, api):
        """PRD §3.7: "the scheduled instant must lie within the inclusive
        interval from `delivery_window_start` to `delivery_window_end`
        (otherwise `ERR_DELIVERY_OUTSIDE_WINDOW`)".

        Design: Corner/validations/delivery_scheduled_outside_window_rejected
        """
        ctx = setup_confirmed_order(units=10)
        resp = api.create_delivery_ticket(
            {
                "order_id": ctx["order"]["id"],
                "order_line_id": ctx["line"]["id"],
                "type": "DELIVERY",
                "scheduled_date": "2027-06-01T00:00:00Z",
                "units": 5,
            },
            SALESREP,
        )
        validate_error(resp, ApiErrorId.ERR_DELIVERY_OUTSIDE_WINDOW)

    def test_delivery_complete_before_scheduled_date_rejected(self, api):
        """PRD §3.7: "Completion, by an administrator or sales rep, requires the
        logical clock to have reached the `scheduled_date` — completing early
        fails with `ERR_DELIVERY_TOO_EARLY`".

        Design: Corner/validations/delivery_complete_before_scheduled_date_rejected
        """
        ctx = setup_confirmed_order(units=10)
        ticket = schedule_delivery(ctx["order"], ctx["line"], 10,
                                   scheduled_date="2027-04-10T00:00:00Z",
                                   ticket_type="PICKUP")

        set_clock("2027-04-09T23:00:00Z")
        resp = api.complete_delivery_ticket(ticket["id"], SALESREP)
        validate_error(resp, ApiErrorId.ERR_DELIVERY_TOO_EARLY)

        set_clock("2027-04-10T00:00:00Z")
        completed = validate_success(api.complete_delivery_ticket(ticket["id"], SALESREP))
        assert completed["status"] == "COMPLETED", (
            "completion at exactly the scheduled_date is admissible"
        )

    def test_delivery_units_exceed_remaining_reserved_rejected(self, api):
        """PRD §3.7: "the ticket's units must not exceed the line's deliverable
        remainder — `reserved_units` minus `delivered_units` minus the units
        already sitting on the line's still-scheduled tickets (otherwise
        `ERR_DELIVERY_EXCEEDS_REMAINING`)".

        Design: Corner/validations/delivery_units_exceed_remaining_reserved_rejected
        """
        ctx = setup_confirmed_order(units=10)
        schedule_delivery(ctx["order"], ctx["line"], 7)

        resp = api.create_delivery_ticket(
            {
                "order_id": ctx["order"]["id"],
                "order_line_id": ctx["line"]["id"],
                "type": "DELIVERY",
                "scheduled_date": "2027-04-11T00:00:00Z",
                "units": 4,
            },
            SALESREP,
        )
        validate_error(resp, ApiErrorId.ERR_DELIVERY_EXCEEDS_REMAINING)

        ticket = validate_success(
            api.create_delivery_ticket(
                {
                    "order_id": ctx["order"]["id"],
                    "order_line_id": ctx["line"]["id"],
                    "type": "DELIVERY",
                    "scheduled_date": "2027-04-11T00:00:00Z",
                    "units": 3,
                },
                SALESREP,
            ),
            expected_status=201,
        )
        assert ticket["status"] == "SCHEDULED"


class TestOrderCancelWithDeliveries:
    def test_cancel_order_with_completed_delivery_rejected(self, api):
        """PRD §3.5: "A `CONFIRMED` order may cancel only while no delivery
        ticket of the order has reached `COMPLETED` (otherwise
        `ERR_ORDER_HAS_DELIVERIES`)".

        Design: Corner/validations/cancel_order_with_completed_delivery_rejected
        """
        ctx = setup_delivered_order(units=10)
        resp = api.cancel_order(ctx["order"]["id"], SALESREP)
        validate_error(resp, ApiErrorId.ERR_ORDER_HAS_DELIVERIES)
        order = validate_success(api.get_order(ctx["order"]["id"], SALESREP))
        assert order["status"] == "CONFIRMED"


class TestDailyCapacityBoundary:
    def _three_confirmed_orders(self, api):
        ctx = setup_market(
            program_overrides={"daily_delivery_capacity_units": 100},
            lot_overrides={"received_units": 10000},
        )
        set_clock("2027-01-10T00:00:00Z")
        orders = []
        for units in (60, 40, 10):
            order = create_draft_order(ctx["grower"], ctx["program"])
            line = add_line(order, ctx["variety"]["id"], units)
            order = confirm_order(order["id"])
            orders.append((order, line))
        return ctx, orders

    def test_load_landing_exactly_at_capacity_allowed(self, api):
        """PRD §3.7: "summing the units of all the program's tickets,
        `SCHEDULED` or `COMPLETED`, whose scheduled instants share the same UTC
        calendar date as the new ticket, that load plus the new units must not
        exceed `daily_delivery_capacity_units`, with a load landing exactly at
        capacity still allowed (otherwise `ERR_DELIVERY_CAPACITY_EXCEEDED`)".

        Design: Difficulty/resource_temporal_overlap/delivery_daily_capacity_aggregate_boundary
        """
        ctx, orders = self._three_confirmed_orders(api)
        first = validate_success(
            api.create_delivery_ticket(
                {
                    "order_id": orders[0][0]["id"],
                    "order_line_id": orders[0][1]["id"],
                    "type": "DELIVERY",
                    "scheduled_date": "2027-04-10T00:00:00Z",
                    "units": 60,
                },
                SALESREP,
            ),
            expected_status=201,
        )
        assert first["status"] == "SCHEDULED"  # load 60 <= 100

        second = validate_success(
            api.create_delivery_ticket(
                {
                    "order_id": orders[1][0]["id"],
                    "order_line_id": orders[1][1]["id"],
                    "type": "DELIVERY",
                    "scheduled_date": "2027-04-10T00:00:00Z",
                    "units": 40,
                },
                SALESREP,
            ),
            expected_status=201,
        )
        assert second["status"] == "SCHEDULED"  # load exactly 100 == capacity

    def test_one_unit_over_capacity_rejected_next_date_ok(self, api):
        """PRD §3.7: "summing the units of all the program's tickets,
        `SCHEDULED` or `COMPLETED`, whose scheduled instants share the same UTC
        calendar date as the new ticket, that load plus the new units must not
        exceed `daily_delivery_capacity_units`, with a load landing exactly at
        capacity still allowed (otherwise `ERR_DELIVERY_CAPACITY_EXCEEDED`)".

        Design: Difficulty/resource_temporal_overlap/delivery_daily_capacity_aggregate_boundary
        """
        ctx, orders = self._three_confirmed_orders(api)
        schedule_delivery(orders[0][0], orders[0][1], 60)
        schedule_delivery(orders[1][0], orders[1][1], 40)

        resp = api.create_delivery_ticket(
            {
                "order_id": orders[2][0]["id"],
                "order_line_id": orders[2][1]["id"],
                "type": "PICKUP",
                "scheduled_date": "2027-04-10T00:00:00Z",
                "units": 1,
            },
            SALESREP,
        )
        validate_error(resp, ApiErrorId.ERR_DELIVERY_CAPACITY_EXCEEDED)

        next_day = validate_success(
            api.create_delivery_ticket(
                {
                    "order_id": orders[2][0]["id"],
                    "order_line_id": orders[2][1]["id"],
                    "type": "PICKUP",
                    "scheduled_date": "2027-04-11T00:00:00Z",
                    "units": 1,
                },
                SALESREP,
            ),
            expected_status=201,
        )
        assert next_day["status"] == "SCHEDULED", (
            "the per-date aggregate resets on the next UTC calendar date"
        )


class TestParallelDimensions:
    def _confirmed_40(self, api):
        return setup_confirmed_order(
            units=40,
            clock="2026-09-15T00:00:00Z",
            program_overrides={
                "early_order_tiers": [
                    {"cutoff_at": "2026-09-30T23:59:59Z", "discount_bps": 1200},
                    {"cutoff_at": "2026-11-15T23:59:59Z", "discount_bps": 1000},
                    {"cutoff_at": "2027-01-15T23:59:59Z", "discount_bps": 600},
                ],
                "prepay_tiers": [
                    {"pay_by": "2026-12-20T23:59:59Z", "discount_bps": 800},
                    {"pay_by": "2027-02-15T23:59:59Z", "discount_bps": 500},
                ],
                "volume_rebate_tiers": [{"min_units": 500, "rebate_bps": 500}],
                "daily_delivery_capacity_units": 1000,
            },
            lot_overrides={"received_units": 1000},
        )

    def test_prepay_advances_payment_but_not_fulfillment(self, api):
        """PRD §3.5: "A seed order is three things at once, and the three evolve
        independently: a lifecycle `status` (`DRAFT`, `CONFIRMED`,
        `COMPLIANCE_HOLD`, `CLOSED`, `CANCELLED`), a parallel money dimension
        `payment_status` (`UNPAID`, `PREPAID`, `INVOICED`, `SETTLED`), and a
        computed fulfillment dimension `fulfillment_status` (`NONE`, `PARTIAL`,
        `DELIVERED`, `RETURNED_PARTIAL`, `RETURNED_FULL`) derived entirely from
        line delivery and return counters per §3.7."

        Design: Difficulty/non_linear_state_machine/order_payment_and_fulfillment_dimensions_evolve_independently
        """
        ctx = self._confirmed_40(api)
        order = ctx["order"]
        assert order["payment_status"] == "UNPAID"
        assert order["fulfillment_status"] == "NONE"

        set_clock("2026-12-01T00:00:00Z")
        # gross 633600 (40 x 15840); 800bps prepay discount 50688; net due 582912
        paid = validate_success(api.prepay_order(order["id"], 582912, SALESREP))
        assert paid["payment_status"] == "PREPAID"
        assert paid["fulfillment_status"] == "NONE", (
            "prepay must not advance the fulfillment dimension"
        )

    def test_deliveries_advance_fulfillment_but_not_payment(self, api):
        """PRD §3.7: "An order is `NONE` when every line has zero delivered and
        zero returned units; `PARTIAL` when some but not all ordered units have
        been delivered and nothing has been returned; `DELIVERED` when every
        line's `delivered_units` equals its `units` with nothing returned".

        Design: Difficulty/non_linear_state_machine/order_payment_and_fulfillment_dimensions_evolve_independently
        """
        ctx = self._confirmed_40(api)
        set_clock("2026-12-01T00:00:00Z")
        paid = validate_success(api.prepay_order(ctx["order"]["id"], 582912, SALESREP))
        assert paid["payment_status"] == "PREPAID"

        # Schedule both tickets before any completion: PRD §3.7's deliverable
        # remainder (reserved_units - delivered_units - scheduled-on-line units)
        # shrinks on completion, so a complete-then-schedule interleaving can
        # never cover the line's full units.
        first = schedule_delivery(ctx["order"], ctx["line"], 25,
                                  scheduled_date="2027-03-10T00:00:00Z")
        second = schedule_delivery(ctx["order"], ctx["line"], 15,
                                   scheduled_date="2027-03-11T00:00:00Z",
                                   ticket_type="PICKUP")

        complete_ticket(first["id"], at_clock="2027-03-10T12:00:00Z")
        order = validate_success(api.get_order(ctx["order"]["id"], SALESREP))
        assert order["fulfillment_status"] == "PARTIAL"
        assert order["payment_status"] == "PREPAID"

        complete_ticket(second["id"], at_clock="2027-03-11T12:00:00Z")
        order = validate_success(api.get_order(ctx["order"]["id"], SALESREP))
        assert order["fulfillment_status"] == "DELIVERED"
        assert order["payment_status"] == "PREPAID", (
            "delivery completion never touches the payment axis"
        )
