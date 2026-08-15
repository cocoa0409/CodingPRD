"""Online orders: parallel payment/fulfillment dimensions, pickup lifecycle,
refund compensation, and the ops-run expiry sweep."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_active_program,
    create_approved_design,
    create_approved_vendor_with_quote,
    create_drop,
    create_online_order,
    create_order_line,
    create_order_payload,
    create_variant,
    drop_transition,
    get_order,
    get_program,
    get_variant,
    make_customer_headers,
    mark_ready_for_pickup,
    run_ops,
    set_clock,
    setup_storefront,
    stock_variant,
    TEST_USERS,
    validate_error,
    validate_success,
)

DIRECTOR = TEST_USERS["director_headers"]
MANAGER = TEST_USERS["store_manager_headers"]
TREASURER = TEST_USERS["treasurer_headers"]


class TestParallelPaymentFulfillmentDims:
    def _setup_ready_order(self, api):
        """Stocked variant + ONLINE CARD order qty 2 (total 5000, margin
        4000), marked READY_FOR_PICKUP."""
        shop = setup_storefront(stock_qty=25)
        program_id = shop["program"]["id"]
        variant_id = shop["variant"]["id"]
        order = create_online_order(
            program_id, variant_id, 2, customer_user_id="cust-10"
        )
        mark_ready_for_pickup(order["id"])
        return program_id, variant_id, order

    def test_partial_refund_moves_only_the_payment_dimension(self, api):
        """PRD §3.7: "Refunds belong to the `Treasurer` and run on a payment
        dimension that is parallel to fulfillment: `payment_status` walks
        `PAID` to `PARTIALLY_REFUNDED` to `REFUNDED` independently of where
        the goods stand."
        PRD §3.7: "While cumulative `refunded_cents` plus the new amount stays
        below `total_cents`, the refund is partial and the order sits in (or
        moves to) `PARTIALLY_REFUNDED`"

        Design: Difficulty/non_linear_state_machine/order_parallel_payment_fulfillment_dims
        """
        program_id, variant_id, order = self._setup_ready_order(api)
        assert order["payment_status"] == "PAID"
        assert order["fulfillment_status"] == "PICKUP_PENDING"

        refunded = validate_success(
            api.refund_order(order["id"], {"amount_cents": 1000}, TREASURER), 200
        )
        assert refunded["payment_status"] == "PARTIALLY_REFUNDED"
        assert refunded["fulfillment_status"] == "READY_FOR_PICKUP", (
            "the fulfillment dimension is untouched by a payment-dimension "
            "refund"
        )
        assert refunded["refunded_cents"] == 1000

    def test_partial_refund_reverses_proportionate_margin(self, api):
        """PRD §3.7: "Every refund claws back profit proportionally: the
        program's `undistributed_profit_cents` decreases by `margin_cents`
        times `amount_cents` divided by `total_cents`, rounded half-up to
        whole cents."
        PRD §3.7: "each online refund releases the reservation proportionally
        for the refunded whole units."

        Design: Difficulty/non_linear_state_machine/order_parallel_payment_fulfillment_dims
        """
        program_id, variant_id, order = self._setup_ready_order(api)
        validate_success(
            api.refund_order(order["id"], {"amount_cents": 1000}, TREASURER), 200
        )
        program = get_program(program_id)
        assert program["undistributed_profit_cents"] == 3200, (
            "margin 4000 recognized at sale; reversal "
            "round_half_up(4000*1000/5000) = 800 leaves 3200"
        )
        assert get_variant(variant_id)["reserved_online_qty"] == 2, (
            "1000 cents covers no whole 2500-cent unit, so the reservation "
            "is untouched"
        )


class TestOnlineReserveRefundConservation:
    def test_online_order_reserves_without_moving_physical_stock(self, api):
        """PRD §3.6: "An `ONLINE` order instead reserves rather than ships:
        each line adds its `qty` to the variant's `reserved_online_qty` and
        nothing leaves the shelf yet."

        Design: Difficulty/compensating_invariant/online_reserve_refund_conserves_inventory
        """
        shop = setup_storefront(stock_qty=25)
        variant_id = shop["variant"]["id"]
        create_online_order(
            shop["program"]["id"], variant_id, 2, customer_user_id="cust-30"
        )
        variant = get_variant(variant_id)
        assert variant["on_hand_qty"] == 25
        assert variant["reserved_online_qty"] == 2

    def test_full_refund_restores_inventory_split_and_profit(self, api):
        """PRD §3.7: "A fully refunded online order that has not been picked
        up also moves its fulfillment to `EXPIRED_RELEASED`, releasing the
        entire remaining reservation."
        PRD §3.7: "an amount bringing the cumulative total exactly to
        `total_cents` completes the refund as `REFUNDED`"
        PRD §3.7: "Every refund claws back profit proportionally: the
        program's `undistributed_profit_cents` decreases by `margin_cents`
        times `amount_cents` divided by `total_cents`, rounded half-up to
        whole cents."

        Design: Difficulty/compensating_invariant/online_reserve_refund_conserves_inventory
        """
        shop = setup_storefront(stock_qty=25)
        program_id = shop["program"]["id"]
        variant_id = shop["variant"]["id"]
        order = create_online_order(
            program_id, variant_id, 2, customer_user_id="cust-30"
        )
        refunded = validate_success(
            api.refund_order(order["id"], {"amount_cents": 5000}, TREASURER), 200
        )
        assert refunded["payment_status"] == "REFUNDED"
        assert refunded["fulfillment_status"] == "EXPIRED_RELEASED"

        variant = get_variant(variant_id)
        assert variant["on_hand_qty"] == 25 and variant["reserved_online_qty"] == 0, (
            "forward reservation plus compensating refund must restore the "
            "exact pre-order inventory split"
        )
        assert get_program(program_id)["undistributed_profit_cents"] == 0, (
            "margin 4000 recognized at sale, then fully reversed by "
            "round_half_up(4000*5000/5000) = 4000"
        )


class TestPickupLifecycle:
    def test_pickup_before_ready_rejected(self, api):
        """PRD §3.6: "Marking an order ready moves `PICKUP_PENDING` to
        `READY_FOR_PICKUP` (from any other state, `ERR_PICKUP_NOT_READY`),
        stamps `ready_at` from the logical clock, and sets `expires_at` to
        `ready_at` plus the program's `pickup_window_days`."
        PRD §3.6: "Pickup moves `READY_FOR_PICKUP` to `PICKED_UP` and is
        allowed only while the clock is at or before `expires_at` —
        afterward, `ERR_PICKUP_EXPIRED`; at pickup, each line decrements both
        `on_hand_qty` and `reserved_online_qty`, and `picked_up_at` is
        stamped."

        Design: Corner/errors/pickup_before_ready_rejected
        """
        shop = setup_storefront(stock_qty=25)
        order = create_online_order(
            shop["program"]["id"], shop["variant"]["id"], 1,
            customer_user_id="cust-83",
        )
        res = api.order_fulfillment_transition(
            order["id"], {"to_state": "PICKED_UP"}, MANAGER
        )
        validate_error(res, ApiErrorId.ERR_PICKUP_NOT_READY, 409)

    def test_pickup_after_expiry_rejected(self, api):
        """PRD §3.6: "Pickup moves `READY_FOR_PICKUP` to `PICKED_UP` and is
        allowed only while the clock is at or before `expires_at` —
        afterward, `ERR_PICKUP_EXPIRED`; at pickup, each line decrements both
        `on_hand_qty` and `reserved_online_qty`, and `picked_up_at` is
        stamped."

        Design: Corner/errors/pickup_after_expiry_rejected
        """
        shop = setup_storefront(stock_qty=25)
        program_id = shop["program"]["id"]
        set_clock("2026-09-05T12:00:00Z")
        order = create_online_order(
            program_id, shop["variant"]["id"], 1, customer_user_id="cust-91"
        )
        ready = mark_ready_for_pickup(order["id"])
        assert ready["fulfillment_status"] == "READY_FOR_PICKUP"

        set_clock("2026-09-13T00:00:00Z")
        res = api.order_fulfillment_transition(
            order["id"], {"to_state": "PICKED_UP"}, MANAGER
        )
        validate_error(res, ApiErrorId.ERR_PICKUP_EXPIRED, 409)


class TestOrderMarginAndStockGates:
    def test_order_margin_accrues_to_program_profit(self, api):
        """PRD §3.6: "The order's `margin_cents` is the sum over its lines of
        the line total minus the line's `qty` times the variant's
        `landed_unit_cost_cents` as it stood at the moment of sale, and that
        margin is immediately added to the program's
        `undistributed_profit_cents`."

        Design: Corner/calculations/order_margin_accrues_to_program_profit
        """
        shop = setup_storefront(stock_qty=25)
        program_id = shop["program"]["id"]
        order = create_online_order(
            program_id, shop["variant"]["id"], 2, customer_user_id="cust-50"
        )
        assert order["total_cents"] == 5000
        assert order["margin_cents"] == 4000
        assert get_program(program_id)["undistributed_profit_cents"] == 4000

    def test_order_with_zero_stock_rejected(self, api):
        """PRD §3.6: "Every line requires the variant's `available_qty` to
        cover its `qty` — one insufficient line fails the entire order with
        `ERR_INSUFFICIENT_STOCK`"

        Design: Corner/errors/order_with_zero_stock_rejected
        """
        shop = setup_storefront(stock_qty=None)
        res = api.create_order(
            create_order_payload(
                shop["program"]["id"],
                "ONLINE",
                "cust-88",
                "CARD",
                [create_order_line(shop["variant"]["id"], 1)],
            ),
            make_customer_headers("cust-88"),
        )
        validate_error(res, ApiErrorId.ERR_INSUFFICIENT_STOCK, 422)

    def test_invalid_enum_value_rejected(self, api):
        """PRD §3.6: "the `channel` field — `EVENT_POS` or `ONLINE` — decides
        the rules."
        PRD §2.8: "Required fields are present, enum values are valid, and
        ranges hold: `qty` at least 1, percentage fields between 0 and 1
        inclusive, `closes_at` strictly after `opens_at`, `ends_at` strictly
        after `starts_at`, `amount_cents` at least 1. Violations are
        `ERR_INVALID_REQUEST`."

        Design: Corner/validations/invalid_enum_value_rejected
        """
        program = create_active_program()
        res = api.create_order(
            {
                "program_id": program["id"],
                "channel": "MAIL",
                "customer_user_id": "cust-60",
                "payment_method": "CARD",
                "lines": [],
            },
            make_customer_headers("cust-60"),
        )
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, 400)


class TestRunOpsCheckpoint:
    def test_run_ops_expires_pickup_and_closes_drop(self, api):
        """PRD §3.1: "each run adds 1 to `ops_run_index`, auto-closes every
        `OPEN` seasonal drop whose `closes_at` the logical clock has reached
        or passed, and expires every online order still `READY_FOR_PICKUP`
        whose `expires_at` the clock has passed (§3.6)."
        PRD §3.6: "an ops run (§3.1) whose clock has passed `expires_at`
        releases the order to `EXPIRED_RELEASED`: the reservation is released
        back to sellable stock, the order is refunded in full —
        `payment_status` becomes `REFUNDED` and `refunded_cents` becomes the
        full `total_cents` — and the program's `undistributed_profit_cents`
        surrenders the order's entire `margin_cents`."

        Design: Corner/cross_cutting_layers/run_ops_expires_pickup_and_closes_drop
        """
        program = create_active_program()
        design = create_approved_design(program["id"])
        drop = create_drop(
            program["id"],
            program["version"],
            name="Fall",
            opens_at="2026-08-01T00:00:00Z",
            closes_at="2026-09-10T00:00:00Z",
        )
        variant = create_variant(
            program["id"], design["id"], size="M", unit_price_cents=2500,
            drop_id=drop["id"],
        )
        vendor = create_approved_vendor_with_quote(program["id"], design["id"])
        stock_variant(program["id"], variant["id"], vendor["id"], 25)

        set_clock("2026-09-05T12:00:00Z")
        drop_transition(drop["id"], "OPEN")
        order = create_online_order(
            program["id"], variant["id"], 1, customer_user_id="cust-90"
        )
        ready = mark_ready_for_pickup(order["id"])
        assert ready["expires_at"] is not None
        assert ready["expires_at"].startswith("2026-09-12T12:00:00"), (
            f"expires_at is ready_at (2026-09-05T12:00) plus the 7-day "
            f"pickup window, got {ready['expires_at']}"
        )

        set_clock("2026-09-13T00:00:00Z")
        program_after = run_ops(program["id"])
        assert program_after["ops_run_index"] == 1

        order_after = get_order(order["id"])
        assert order_after["fulfillment_status"] == "EXPIRED_RELEASED"
        assert order_after["payment_status"] == "REFUNDED"
        assert order_after["refunded_cents"] == 2500

        drop_after = validate_success(api.get_seasonal_drop(drop["id"], TREASURER), 200)
        assert drop_after["status"] == "CLOSED", (
            "closes_at 2026-09-10 has been reached by the 2026-09-13 clock"
        )

        variant_after = get_variant(variant["id"])
        assert variant_after["on_hand_qty"] == 25
        assert variant_after["reserved_online_qty"] == 0
        assert variant_after["sellable"] is False, (
            "a variant whose drop is no longer OPEN is not sellable"
        )
        assert get_program(program["id"])["undistributed_profit_cents"] == 0, (
            "margin 2000 recognized at sale is fully surrendered at expiry"
        )
