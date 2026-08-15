"""Order fulfillment: reservation, backorder waterfall, staging, completion (PRD §2.10, §3.7, §3.8)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_stock_invariants,
    create_delivered_order,
    create_kit_payload,
    create_kitted_order,
    create_order_line_payload,
    create_order_payload,
    create_payment_payload,
    create_picked_up_order,
    create_submitted_order,
    get_order_line,
    get_stock_row,
    receive_stock,
    setup_branch_product_account,
    stage_kit,
    validate_error,
    validate_success,
)

MANAGER = TEST_USERS["manager_headers"]
REP = TEST_USERS["counterrep_headers"]
SALES = TEST_USERS["sales_headers"]
WAREHOUSE = TEST_USERS["warehouse_headers"]


class TestReservationAndBackorders:
    def test_reserve_then_cancel_conserves_inventory_midstate(self, api):
        """PRD §2.10: "Stock is tracked per branch and per product on an
        inventory record holding `on_hand` (physical units present), `reserved`
        (units committed to allocated order lines), and `available` (always
        exactly `on_hand` minus `reserved` — an invariant the system maintains
        at all times)."
        PRD §3.7: "a line whose product's `available` covers its `qty_ordered`
        becomes `ALLOCATED` with `qty_allocated` set to the full quantity and
        the stock record's `reserved` raised accordingly".

        Submitting P1 x7 against 20 on hand reserves 7: (20, 7, 13).

        Design: Difficulty/compensating_invariant/reserve_cancel_conserves_inventory
        """
        branch, product, account = setup_branch_product_account(stock=20)
        create_submitted_order(account["id"], branch["id"], [(product["id"], 7)])
        row = get_stock_row(branch["id"], product["id"])
        assert_stock_invariants(row)
        assert (row["on_hand"], row["reserved"], row["available"]) == (20, 7, 13), (
            f"mid-state must be (20, 7, 13), got {(row['on_hand'], row['reserved'], row['available'])}"
        )

    def test_reserve_then_cancel_conserves_inventory_restored(self, api):
        """PRD §3.7: "Cancelling from `OPEN` or `PICKING` unwinds the world: each line releases its reservation (the stock record's `reserved` drops by the line's `qty_allocated`), any active delivery booking is released (the slot's `booked_cubes` drops by the order's `cubes_total`, and a `FULL` slot recomputes to `OPEN`), lines in `OPEN`, `ALLOCATED`, or `BACKORDERED` fall to `CANCELLED` (allocated and backordered lines additionally return their reserved quantities), and the account's forward exposure is recomputed."

        The cancel compensates the reserve exactly: the (on_hand, reserved,
        available) triple returns to the pre-submit (20, 0, 20) with zero drift.

        Design: Difficulty/compensating_invariant/reserve_cancel_conserves_inventory
        """
        branch, product, account = setup_branch_product_account(stock=20)
        order, _ = create_submitted_order(account["id"], branch["id"], [(product["id"], 7)])
        validate_success(api.cancel_order(order["id"], REP))
        row = get_stock_row(branch["id"], product["id"])
        assert_stock_invariants(row)
        assert (row["on_hand"], row["reserved"], row["available"]) == (20, 0, 20), (
            f"post-cancel triple must equal the pre-submit (20, 0, 20), got {(row['on_hand'], row['reserved'], row['available'])}"
        )

    def test_available_invariant_reconciles_through_fulfill(self, api, warehouse_headers):
        """PRD §2.10: "`available` (always exactly `on_hand` minus `reserved` —
        an invariant the system maintains at all times)".
        PRD §3.8: "Marking staged picks every `ALLOCATED` line: the line's
        `qty_fulfilled` is set to its `qty_allocated` (which is retained for
        audit), the line moves to `FILLED`, and the stock record for each line's
        product has both `on_hand` and `reserved` reduced by the fulfilled
        quantity."

        Submit of x4 against 10 moves (10, 4, 6); mark-staged moves (6, 0, 6).

        Design: Corner/cross_cutting_layers/derived_available_reconciles_through_fulfill
        """
        branch, product, account = setup_branch_product_account(stock=10)
        order, _ = create_submitted_order(
            account["id"], branch["id"], [(product["id"], 4)], will_call=True
        )
        row1 = get_stock_row(branch["id"], product["id"])
        assert (row1["on_hand"], row1["reserved"], row1["available"]) == (10, 4, 6)
        assert_stock_invariants(row1)

        validate_success(api.mark_staged(order["id"], warehouse_headers))
        row2 = get_stock_row(branch["id"], product["id"])
        assert (row2["on_hand"], row2["reserved"], row2["available"]) == (6, 0, 6), (
            f"pick must debit both on_hand and reserved, got {(row2['on_hand'], row2['reserved'], row2['available'])}"
        )
        assert_stock_invariants(row2)

    def test_submit_response_reflects_reservation_immediately(self, api, counterrep_headers):
        """PRD §2.4: "Cascading side effects are mutations like any other. When one operation ripples into another resource — a receipt that allocates a waiting order line, a delivered order that debits an account balance, a booking that fills a truck window — each affected resource has its own `updated_at` refreshed and its own `version` incremented. All such cascades settle immediately: every mutation and every downstream effect of a request is visible in that request's response envelope, with no deferred or eventually-consistent states."
        PRD §2.11: "Every product declares `cubes_per_unit`, and an order's `cubes_total` is the sum, over its non-`CANCELLED` lines, of each line's `qty_allocated` multiplied by its product's `cubes_per_unit`; this load is the basis for truck booking."

        The submit response itself carries the post-submit fulfillment status
        (OPEN, or PICKING once the automatic bubble-up of §3.7 — "whether by
        the initial reservation" — is reflected in the same envelope per §2.4),
        the recomputed total 20500 (18000 + 2500 freight), and cubes_total 20.

        Design: Corner/consistency_model/submit_response_reflects_reservation_immediately
        """
        branch, product, account = setup_branch_product_account(stock=3)
        order = validate_success(
            api.create_order(create_order_payload(account["id"], branch["id"]), counterrep_headers), 201
        )
        validate_success(
            api.add_order_line(order["id"], create_order_line_payload(product["id"], 2), counterrep_headers),
            201,
        )
        submitted = validate_success(api.submit_order(order["id"], counterrep_headers))
        assert submitted["fulfillment_status"] in ("OPEN", "PICKING"), (
            f"submit must leave DRAFT, got {submitted['fulfillment_status']}"
        )
        assert submitted["total_cents"] == 20500, (
            f"18000 + 2500 freight must be visible in the submit envelope, got {submitted['total_cents']}"
        )
        assert submitted["cubes_total"] == 20


class TestReceiptCascade:
    def _setup_cascade(self, api):
        """Order P1 x5 against stock 2 (line BACKORDERED with 2 allocated) + kit over the line."""
        branch, product, account = setup_branch_product_account(stock=2)
        order, line_ids = create_submitted_order(
            account["id"], branch["id"], [(product["id"], 5)], will_call=True
        )
        kit = validate_success(api.create_kit(
            order["id"], create_kit_payload([line_ids[0]]), SALES
        ), 201)
        return branch, product, order, line_ids[0], kit

    def test_receipt_allocates_waiting_line(self, api):
        """PRD §2.10: "Each candidate takes the smaller of its remaining
        shortage and the currently available stock; partial fills are allowed,
        and a candidate later in the queue simply gets nothing when stock
        exhausts. A candidate whose allocation reaches its full ordered quantity
        flips from `BACKORDERED` to `ALLOCATED`."

        A 3-unit receipt completes the waiting line's shortage: it lands
        ALLOCATED with qty_allocated 5 and the stock record reads (5, 5, 0).

        Design: Difficulty/transitive_cascade/receipt_stocks_backorder_line_then_waves_order
        """
        branch, product, order, line_id, _ = self._setup_cascade(api)
        receive_stock(branch["id"], product["id"], 3, 5000)

        line = get_order_line(line_id, order["id"])
        assert line["status"] == "ALLOCATED"
        assert line["qty_allocated"] == 5
        assert line["qty_backordered"] == 0
        row = get_stock_row(branch["id"], product["id"])
        assert (row["on_hand"], row["reserved"], row["available"]) == (5, 5, 0)

    def test_receipt_waves_order_and_assembles_kit(self, api):
        """PRD §3.7: "the moment every non-`CANCELLED` line is `ALLOCATED` or
        `FILLED` — whether by the initial reservation, by the backorder
        waterfall, or by a substitute approval — the order bubbles automatically
        from `OPEN` to `PICKING`."
        PRD §3.8: "it starts `DRAFT` with no bin or window assigned (`staging_bin`, `staged_window_start`, and `staged_window_end` all null), and promotes automatically to `ASSEMBLED` the moment every member line is `ALLOCATED` or `FILLED` — a condition re-evaluated on line allocation, on kit creation (so a kit built over already-allocated lines assembles immediately), and on substitute approval."

        No direct order or kit call fires these — the receipt's cascade waves
        the order to PICKING and the kit to ASSEMBLED.

        Design: Difficulty/transitive_cascade/receipt_stocks_backorder_line_then_waves_order
        """
        branch, product, order, _, kit = self._setup_cascade(api)
        kit_before = validate_success(api.get_kit(kit["id"], SALES))
        assert kit_before["status"] == "DRAFT"

        receive_stock(branch["id"], product["id"], 3, 5000)

        order_after = validate_success(api.get_order(order["id"], SALES))
        assert order_after["fulfillment_status"] == "PICKING", (
            f"allocation bubble-up must wave the order to PICKING, got {order_after['fulfillment_status']}"
        )
        kit_after = validate_success(api.get_kit(kit["id"], SALES))
        assert kit_after["status"] == "ASSEMBLED", (
            f"kit posture derives from member lines, got {kit_after['status']}"
        )

    def test_backorder_fifo_oldest_line_first(self, api, sales_headers):
        """PRD §2.10: "For the affected branch-and-product pair, waiting
        backordered lines are processed oldest first by the line's `created_at`,
        with ties broken by the owning order's `created_at` — never by resource
        id."

        A 5-unit receipt fully fills the older order's line and gives the newer
        order's line nothing; the older order waves to PICKING while the newer
        stays OPEN.

        Design: Corner/calculations/backorder_fifo_oldest_line_first
        """
        branch, product, account = setup_branch_product_account(
            stock=0, account_overrides={"credit_limit_cents": 100000000}
        )
        order1, line1 = create_submitted_order(account["id"], branch["id"], [(product["id"], 5)])
        order2, line2 = create_submitted_order(account["id"], branch["id"], [(product["id"], 5)])

        receive_stock(branch["id"], product["id"], 5, 5000)

        l1 = get_order_line(line1[0], order1["id"])
        l2 = get_order_line(line2[0], order2["id"])
        assert l1["status"] == "ALLOCATED" and l1["qty_allocated"] == 5, (
            "the oldest created line wins the whole receipt"
        )
        assert l2["status"] == "BACKORDERED" and l2["qty_allocated"] == 0, (
            "stock exhausted — the later line gets nothing"
        )
        o1 = validate_success(api.get_order(order1["id"], sales_headers))
        o2 = validate_success(api.get_order(order2["id"], sales_headers))
        assert o1["fulfillment_status"] == "PICKING"
        assert o2["fulfillment_status"] == "OPEN"


class TestCompletionGates:
    def test_delivered_order_cannot_cancel(self, api, counterrep_headers, sales_headers):
        """PRD §3.7: "Cancellation is available to a `CounterRep` from `DRAFT`,
        `OPEN`, or `PICKING`." DELIVERED is terminal for the fulfillment
        dimension, so the cancel is rejected with `ERR_INVALID_STATE`.

        Design: Corner/state_machines/delivered_order_cannot_cancel
        """
        branch, product, account = setup_branch_product_account(stock=2)
        order, _ = create_delivered_order(account["id"], branch["id"], [(product["id"], 2)])
        assert order["fulfillment_status"] == "DELIVERED"

        res = api.cancel_order(order["id"], counterrep_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
        after = validate_success(api.get_order(order["id"], sales_headers))
        assert after["fulfillment_status"] == "DELIVERED"

    def test_dispatch_without_booking_rejected(self, api, warehouse_headers, sales_headers):
        """PRD §3.8: "A delivery order is dispatched by a `WarehouseLead`, which requires an active delivery booking — an order whose `delivery_slot_id` is null cannot dispatch and is rejected with `ERR_INVALID_STATE`; dispatch moves the order to `DISPATCHED` and releases every `STAGED` kit on the order to `RELEASED`."

        Design: Corner/state_machines/dispatch_without_booking_rejected
        """
        branch, product, account = setup_branch_product_account(stock=2)
        order, _ = create_submitted_order(account["id"], branch["id"], [(product["id"], 1)])
        validate_success(api.mark_staged(order["id"], warehouse_headers))

        res = api.dispatch_order(order["id"], warehouse_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
        after = validate_success(api.get_order(order["id"], sales_headers))
        assert after["fulfillment_status"] == "STAGED"

    def test_pickup_non_willcall_rejected(self, api, counterrep_headers, warehouse_headers, sales_headers):
        """PRD §3.8: "a `CounterRep` runs the pickup, which requires the order's
        `will_call` flag be true (a pickup attempted on a delivery order is
        rejected with `ERR_INVALID_STATE`)".

        Design: Corner/state_machines/pickup_non_willcall_rejected
        """
        branch, product, account = setup_branch_product_account(stock=2)
        order, _ = create_submitted_order(
            account["id"], branch["id"], [(product["id"], 1)], will_call=False
        )
        validate_success(api.mark_staged(order["id"], warehouse_headers))

        res = api.pickup_order(order["id"], counterrep_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
        after = validate_success(api.get_order(order["id"], sales_headers))
        assert after["fulfillment_status"] == "STAGED"
        assert after["payment_status"] == "UNINVOICED"

    def test_mark_staged_blocked_until_kits_staged(self, api, warehouse_headers, counterrep_headers):
        """PRD §3.8: "With the order `PICKING`, a `WarehouseLead` marks it
        staged. For a will-call order that has at least one kit, every kit of
        the order must already be `STAGED` — otherwise the request is rejected
        with `ERR_INVALID_STATE`; a will-call order with no kits stages
        directly."
        PRD §3.8: "moves the order from `STAGED` to terminal `PICKED_UP`, and
        likewise releases its `STAGED` kits to `RELEASED`."

        Design: Corner/state_machines/mark_staged_blocked_until_kits_staged
        """
        branch, product, account = setup_branch_product_account(stock=5)
        order, _, kit_ids = create_kitted_order(account["id"], branch["id"], product["id"])

        res = api.mark_staged(order["id"], warehouse_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)

        stage_kit(kit_ids[0], bin_label="B1")
        staged = validate_success(api.mark_staged(order["id"], warehouse_headers))
        assert staged["fulfillment_status"] == "STAGED"

        picked = validate_success(api.pickup_order(order["id"], counterrep_headers))
        assert picked["fulfillment_status"] == "PICKED_UP"
        kit_after = validate_success(api.get_kit(kit_ids[0], SALES))
        assert kit_after["status"] == "RELEASED"


class TestParallelDimensions:
    def _setup_two_orders(self):
        """Order A picked up (INVOICED 38500); order B submitted (UNINVOICED 20500)."""
        branch, product, account = setup_branch_product_account(stock=20)
        order_a, _ = create_picked_up_order(account["id"], branch["id"], [(product["id"], 4)])
        order_b, _ = create_submitted_order(account["id"], branch["id"], [(product["id"], 2)], will_call=True)
        return branch, product, account, order_a, order_b

    def test_payment_moves_payment_status_only(self, api, sales_headers):
        """PRD §3.8: "The order's two dimensions then evolve independently again
        until payments carry `payment_status` to terminal `PAID`."
        PRD §3.3: "An order whose allocations reach its `total_cents` flips from
        `INVOICED` to `PAID`, its terminal payment state."

        Paying order A in full flips payment_status to PAID while its
        fulfillment stays PICKED_UP.

        Design: Difficulty/non_linear_state_machine/order_payment_fulfillment_parallel_independence
        """
        _, _, account, order_a, _ = self._setup_two_orders()
        validate_success(api.create_payment(
            account["id"],
            create_payment_payload(38500, method="ACH",
                                   allocations=[{"order_id": order_a["id"], "amount_cents": 38500}]),
            REP,
        ), 201)
        a = validate_success(api.get_order(order_a["id"], sales_headers))
        assert a["payment_status"] == "PAID"
        assert a["fulfillment_status"] == "PICKED_UP", (
            "the payment must not move the fulfillment dimension"
        )
        acct = validate_success(api.get_account(account["id"], sales_headers))
        assert acct["outstanding_balance_cents"] == 0

    def test_cancel_moves_fulfillment_status_only(self, api, sales_headers):
        """PRD §3.8: "The order's two dimensions then evolve independently again
        until payments carry `payment_status` to terminal `PAID`."
        PRD §3.7: "Either way the order lands in terminal `CANCELLED` with its
        `version` incremented."

        Cancelling the still-uninvoiced order B lands it in CANCELLED while its
        payment_status stays UNINVOICED.

        Design: Difficulty/non_linear_state_machine/order_payment_fulfillment_parallel_independence
        """
        _, _, _, _, order_b = self._setup_two_orders()
        validate_success(api.cancel_order(order_b["id"], REP))
        b = validate_success(api.get_order(order_b["id"], sales_headers))
        assert b["fulfillment_status"] == "CANCELLED"
        assert b["payment_status"] == "UNINVOICED", (
            "the cancel must not move the payment dimension"
        )
