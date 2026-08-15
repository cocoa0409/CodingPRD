"""POS sales: drawer gating, drawer/stock side effects, per-line rounding."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_order,
    create_event,
    create_open_event,
    create_order_line,
    create_order_payload,
    create_pos_order,
    get_event,
    get_program,
    get_variant,
    make_cashier_headers,
    open_drawer,
    setup_storefront,
    TEST_USERS,
    validate_error,
    validate_success,
)

DIRECTOR = TEST_USERS["director_headers"]
MANAGER = TEST_USERS["store_manager_headers"]
TREASURER = TEST_USERS["treasurer_headers"]


class TestPosOrderRequiresEventOpen:
    def test_pos_order_on_scheduled_event_rejected(self, api):
        """PRD §3.6: "The event must be `OPEN`, else `ERR_DRAWER_NOT_OPEN`."

        Design: Difficulty/cross_entity_state_dependency/pos_order_requires_event_open
        """
        shop = setup_storefront(stock_qty=25)
        program_id = shop["program"]["id"]
        event = create_event(program_id, register="GYM-C")
        res = api.create_order(
            create_order_payload(
                program_id,
                "EVENT_POS",
                "walkup",
                "CASH",
                [create_order_line(shop["variant"]["id"], 1)],
                event_id=event["id"],
            ),
            make_cashier_headers("cashier-01"),
        )
        validate_error(res, ApiErrorId.ERR_DRAWER_NOT_OPEN, 409)

    def test_pos_order_succeeds_after_drawer_open(self, api):
        """PRD §3.6: "The event must be `OPEN`, else `ERR_DRAWER_NOT_OPEN`."
        PRD §3.6: "Stock leaves the shelf immediately — each line decrements
        its variant's `on_hand_qty` — and the drawer's running totals absorb
        the sale: the order total lands on `cash_sales_cents` for a `CASH`
        payment or on `card_sales_cents` for a `CARD` one."

        Design: Difficulty/cross_entity_state_dependency/pos_order_requires_event_open
        """
        shop = setup_storefront(stock_qty=25)
        program_id = shop["program"]["id"]
        variant_id = shop["variant"]["id"]
        event = create_event(program_id, register="GYM-C")
        open_drawer(event["id"], 10000, "cashier-01")

        order = validate_success(
            api.create_order(
                create_order_payload(
                    program_id,
                    "EVENT_POS",
                    "walkup",
                    "CASH",
                    [create_order_line(variant_id, 1)],
                    event_id=event["id"],
                ),
                make_cashier_headers("cashier-01"),
            ),
            201,
        )
        assert_order(order)
        assert order["total_cents"] == 2500
        assert order["payment_status"] == "PAID"
        assert order["fulfillment_status"] == "POS_FULFILLED"
        event_after = get_event(event["id"])
        assert event_after["cash_sales_cents"] == 2500


class TestPosSaleSideEffects:
    def test_pos_sale_updates_drawer_and_stock(self, api):
        """PRD §3.6: "Stock leaves the shelf immediately — each line
        decrements its variant's `on_hand_qty` — and the drawer's running
        totals absorb the sale: the order total lands on `cash_sales_cents`
        for a `CASH` payment or on `card_sales_cents` for a `CARD` one."
        PRD §3.6: "The order's `margin_cents` is the sum over its lines of the
        line total minus the line's `qty` times the variant's
        `landed_unit_cost_cents` as it stood at the moment of sale, and that
        margin is immediately added to the program's
        `undistributed_profit_cents`."

        Design: Corner/state_machines/pos_sale_updates_drawer_and_stock
        """
        shop = setup_storefront(stock_qty=25)
        program_id = shop["program"]["id"]
        variant_id = shop["variant"]["id"]
        event = create_open_event(program_id, register="GYM-S")

        order = validate_success(
            api.create_order(
                create_order_payload(
                    program_id,
                    "EVENT_POS",
                    "walkup",
                    "CASH",
                    [create_order_line(variant_id, 2)],
                    event_id=event["id"],
                ),
                make_cashier_headers("cashier-01"),
            ),
            201,
        )
        assert order["total_cents"] == 5000
        assert order["margin_cents"] == 4000, (
            f"5000 - 2 * 500 landed cost = 4000, got {order['margin_cents']}"
        )

        assert get_event(event["id"])["cash_sales_cents"] == 5000
        assert get_variant(variant_id)["on_hand_qty"] == 23
        assert get_program(program_id)["undistributed_profit_cents"] == 4000


class TestOrderTotalPerLineRounding:
    def _setup(self, api):
        shop = setup_storefront(
            stock_qty=25, unit_price_cents=333, unit_cost_cents=100
        )
        program_id = shop["program"]["id"]
        event = create_open_event(program_id, register="GYM-A")
        return shop, program_id, event

    def test_per_line_rounding_then_sum(self, api):
        """PRD §3.6: "each line total is the variant's current
        `unit_price_cents` times the line's `qty` times one minus the line's
        `discount_pct`, rounded half-up to whole cents, and `total_cents` is
        the sum of those already-rounded line totals — the per-line rounding
        happens first and the summing second, in that pinned order."
        PRD §3.6: "Three lines at 333 cents with a ten-percent line discount
        make the stakes concrete: per-line rounding yields 300 cents a line
        and a 900-cent order, while summing first and rounding once would
        yield 899."

        Design: Difficulty/combinatorial_formula/order_total_per_line_rounding
        """
        shop, program_id, event = self._setup(api)
        lines = [
            create_order_line(shop["variant"]["id"], 1, discount_pct=0.10)
            for _ in range(3)
        ]
        order = validate_success(
            api.create_order(
                create_order_payload(
                    program_id, "EVENT_POS", "walkup", "CASH", lines,
                    event_id=event["id"],
                ),
                make_cashier_headers("cashier-01"),
            ),
            201,
        )
        assert order["total_cents"] == 900, (
            "round_half_up(333 * 0.9) = 300 per line, summed 300+300+300 = "
            "900; NOT 899 from sum-then-round"
        )

    def test_per_line_rounding_visible_in_drawer_total(self, api):
        """PRD §3.6: "Three lines at 333 cents with a ten-percent line
        discount make the stakes concrete: per-line rounding yields 300 cents
        a line and a 900-cent order, while summing first and rounding once
        would yield 899."
        PRD §3.6: "the drawer's running totals absorb the sale: the order
        total lands on `cash_sales_cents` for a `CASH` payment"

        Design: Difficulty/combinatorial_formula/order_total_per_line_rounding
        """
        shop, program_id, event = self._setup(api)
        lines = [
            create_order_line(shop["variant"]["id"], 1, discount_pct=0.10)
            for _ in range(3)
        ]
        validate_success(
            api.create_order(
                create_order_payload(
                    program_id, "EVENT_POS", "walkup", "CASH", lines,
                    event_id=event["id"],
                ),
                make_cashier_headers("cashier-01"),
            ),
            201,
        )
        assert get_event(event["id"])["cash_sales_cents"] == 900


class TestRefundCap:
    def test_refund_exceeds_paid_rejected(self, api):
        """PRD §3.7: "While cumulative `refunded_cents` plus the new amount
        stays below `total_cents`, the refund is partial and the order sits in
        (or moves to) `PARTIALLY_REFUNDED`; an amount bringing the cumulative
        total exactly to `total_cents` completes the refund as `REFUNDED`;
        anything beyond that is `ERR_REFUND_EXCEEDS_PAID`."

        Design: Corner/validations/refund_exceeds_paid_rejected
        """
        shop = setup_storefront(stock_qty=25)
        program_id = shop["program"]["id"]
        event = create_open_event(program_id, register="GYM-R")
        order = create_pos_order(
            program_id, event["id"], shop["variant"]["id"], 1, payment_method="CASH"
        )
        res = api.refund_order(order["id"], {"amount_cents": 2501}, TREASURER)
        validate_error(res, ApiErrorId.ERR_REFUND_EXCEEDS_PAID, 422)
