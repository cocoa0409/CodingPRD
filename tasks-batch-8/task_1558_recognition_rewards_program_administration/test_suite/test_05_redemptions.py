"""Redemption orders: escrow lifecycle, balance/inventory/window gates,
vendor capacity scheduling, suspension gating, returns, and anomaly flags."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_employee_ledger_reconciles,
    create_catalog_item,
    create_catalog_item_payload,
    create_redemption_order_payload,
    create_vendor,
    deliver_redemption_order,
    get_success_data,
    make_employee_headers,
    setup_catalog,
    setup_employee_with_grant,
    validate_error,
    validate_paginated,
    validate_success,
)

VOPS = TEST_USERS["vendor_ops_headers"]


class TestRedemptionBalanceGate:
    def test_order_at_exact_balance_succeeds_then_next_rejected(
        self, api, hr_admin_headers
    ):
        """PRD §3.5: "The employee's `available_points` must cover the order's
        `points_total` — computed as the item's `point_cost` multiplied by
        `quantity` and snapshotted at creation — else `ERR_INSUFFICIENT_POINTS`."

        Design: Difficulty/boundary_precision_check/redemption_at_exact_balance
        """
        ctx = setup_employee_with_grant(1000)
        employee = ctx["employee"]
        vendor, item_big = setup_catalog(item_overrides={
            "sku": "BIG", "name": "Big", "point_cost": 1000, "cash_value_cents": 5000,
        })
        item_tiny = create_catalog_item(
            vendor["id"], sku="TINY", name="Tiny", point_cost=1,
            cash_value_cents=5,
        )

        order = None
        order_res = api.create_redemption_order(
            create_redemption_order_payload(item_big["id"], idempotency_key="bp2-r1"),
            make_employee_headers(employee["id"]),
        )
        order = validate_success(order_res, 201)
        assert order["fulfillment_status"] == "PENDING_SUBMISSION"

        balance = validate_success(api.get_employee(employee["id"], hr_admin_headers), 200)
        assert balance["available_points"] == 0
        assert balance["held_points"] == 1000

        res = api.create_redemption_order(
            create_redemption_order_payload(item_tiny["id"], idempotency_key="bp2-r2"),
            make_employee_headers(employee["id"]),
        )
        validate_error(res, ApiErrorId.ERR_INSUFFICIENT_POINTS)

    def test_exact_balance_order_leaves_zero_available_and_full_hold(
        self, api, hr_admin_headers
    ):
        """PRD §3.5: "A created order opens in `fulfillment_status`
        `PENDING_SUBMISSION` with `escrow_status` `HELD`: a `HOLD` ledger entry
        moves `points_total` from the employee's `available_points` into
        `held_points`."

        Design: Difficulty/boundary_precision_check/redemption_at_exact_balance
        """
        ctx = setup_employee_with_grant(1000)
        employee = ctx["employee"]
        _, item = setup_catalog(item_overrides={
            "sku": "EXACT", "name": "Exact", "point_cost": 1000,
            "cash_value_cents": 5000,
        })
        order_res = api.create_redemption_order(
            create_redemption_order_payload(item["id"], idempotency_key="bp2b-r1"),
            make_employee_headers(employee["id"]),
        )
        order = validate_success(order_res, 201)
        assert order["escrow_status"] == "HELD"
        balance = validate_success(api.get_employee(employee["id"], hr_admin_headers), 200)
        assert balance["available_points"] == 0
        assert balance["held_points"] == 1000


class TestRedemptionQuantityGate:
    def test_quantity_out_of_range_rejected(self, api, hr_admin_headers):
        """PRD §2.8 stage 4: "Required fields are present, types are valid,
        enum members are valid, and integers are in range — including
        `points_requested` being at least 1 and at most the program's
        `max_points_per_nomination`, redemption `quantity` between 1 and 5
        inclusive (`ERR_INVALID_QUANTITY`), `period_month` between 1 and 12
        inclusive, and `tax_year` between 2000 and 2100 inclusive
        (`ERR_INVALID_TAX_YEAR`) — on all mutating endpoints
        (`ERR_INVALID_REQUEST` unless a more specific error applies)."

        Design: Corner/validations/redemption_quantity_out_of_range
        """
        ctx = setup_employee_with_grant(
            100000, program_overrides={"max_points_per_nomination": 100000},
        )
        _, item = setup_catalog()
        res = api.create_redemption_order(
            create_redemption_order_payload(item["id"], quantity=6,
                                            idempotency_key="val-qty-r1"),
            make_employee_headers(ctx["employee"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_INVALID_QUANTITY)


class TestRedemptionWindowGate:
    def test_window_beats_balance_on_redeem(self, api, hr_admin_headers):
        """PRD §2.8: "when several checks would fail, the earliest one in this
        order wins, and its error is the one returned."
        PRD §2.8: "The catalog item's availability window
        contains the current logical time and the item is `ACTIVE`
        (`ERR_CATALOG_ITEM_UNAVAILABLE`); a new budget window does not overlap
        an existing one for the same program and department
        (`ERR_BUDGET_PERIOD_OVERLAP`); a return falls within fourteen days of
        delivery and the item is not a gift card (`ERR_RETURN_NOT_ALLOWED`);
        the requested nomination type is enabled in program configuration
        (`ERR_NOMINATION_TYPE_DISABLED`)."
        PRD §2.8: "The redeeming employee's `available_points`
        cover the order's `points_total` (`ERR_INSUFFICIENT_POINTS`)."

        Design: Difficulty/priority_pair_validation_conflict/window_beats_balance_on_redeem
        """
        ctx = setup_employee_with_grant(1)  # spend it below; employee ends at 0
        employee = ctx["employee"]
        _, open_item = setup_catalog(item_overrides={
            "sku": "OPEN", "name": "Open", "point_cost": 1, "cash_value_cents": 5,
        })
        # Drain the single granted point so the balance is exactly zero.
        drain = api.create_redemption_order(
            create_redemption_order_payload(open_item["id"], idempotency_key="pp3-drain"),
            make_employee_headers(employee["id"]),
        )
        validate_success(drain, 201)

        _, future_item = setup_catalog(item_overrides={
            "sku": "FUTURE", "name": "Future Item", "point_cost": 100,
            "cash_value_cents": 500,
            "active_window_start": "2026-09-01T00:00:00Z",
            "active_window_end": "2026-10-01T00:00:00Z",
        })
        res = api.create_redemption_order(
            create_redemption_order_payload(future_item["id"], idempotency_key="pp3-r1"),
            make_employee_headers(employee["id"]),
        )
        # Window (stage 13) wins over the zero-balance failure (stage 17).
        validate_error(res, ApiErrorId.ERR_CATALOG_ITEM_UNAVAILABLE)

    def test_unopened_window_rejected_even_with_sufficient_balance(
        self, api, hr_admin_headers
    ):
        """PRD §3.5: "The item must be purchasable at the current logical
        instant — `status` `ACTIVE` and the instant inside the half-open
        window — or the order is rejected with `ERR_CATALOG_ITEM_UNAVAILABLE`."

        Design: Difficulty/priority_pair_validation_conflict/window_beats_balance_on_redeem
        """
        ctx = setup_employee_with_grant(1000)
        _, future_item = setup_catalog(item_overrides={
            "sku": "FUT2", "name": "Future", "point_cost": 100,
            "cash_value_cents": 500,
            "active_window_start": "2026-09-01T00:00:00Z",
            "active_window_end": "2026-10-01T00:00:00Z",
        })
        res = api.create_redemption_order(
            create_redemption_order_payload(future_item["id"], idempotency_key="pp3b-r1"),
            make_employee_headers(ctx["employee"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_CATALOG_ITEM_UNAVAILABLE)


class TestInventoryGate:
    def test_out_of_stock_rejected_then_cancel_restores_inventory(
        self, api, vendor_ops_headers
    ):
        """PRD §3.5: "Stocked items must have at least `quantity` on hand,
        else `ERR_ITEM_OUT_OF_STOCK`, and the inventory count drops at order
        creation."
        PRD §3.5: "Cancellation lands the order in `CANCELLED` with escrow
        `REFUNDED`, writes a `REFUND` ledger entry returning the full
        `points_total` from held back to available points, restores the
        catalog item's inventory by `quantity` when the item is stocked".

        Design: Corner/validations/out_of_stock_rejected_then_restocked
        """
        ctx = setup_employee_with_grant(1000)
        employee = ctx["employee"]
        _, item = setup_catalog(item_overrides={
            "sku": "RARE", "name": "Rare", "inventory_quantity": 1,
        })
        first = validate_success(api.create_redemption_order(
            create_redemption_order_payload(item["id"], idempotency_key="val-inv-r1"),
            make_employee_headers(employee["id"]),
        ), 201)

        res = api.create_redemption_order(
            create_redemption_order_payload(item["id"], idempotency_key="val-inv-r2"),
            make_employee_headers(employee["id"]),
        )
        validate_error(res, ApiErrorId.ERR_ITEM_OUT_OF_STOCK)

        get_success_data(api.cancel_redemption_order(
            first["id"], make_employee_headers(employee["id"])
        ))
        third = validate_success(api.create_redemption_order(
            create_redemption_order_payload(item["id"], idempotency_key="val-inv-r3"),
            make_employee_headers(employee["id"]),
        ), 201)
        assert third["fulfillment_status"] == "PENDING_SUBMISSION"

        reloaded = validate_success(api.get_catalog_item(item["id"], vendor_ops_headers), 200)
        # Cancel restored 1; the third order consumed it again.
        assert reloaded["inventory_quantity"] == 0


class TestParallelEscrowDimensions:
    def test_submit_holds_escrow_then_cancel_flips_only_escrow(
        self, api, hr_admin_headers
    ):
        """PRD §3.5: "From `PENDING_SUBMISSION` or `SUBMITTED` — and only those
        states — the owning employee, or an `HRAdmin`, may cancel".
        PRD §3.5: "Cancellation lands the order in `CANCELLED` with escrow
        `REFUNDED`, writes a `REFUND` ledger entry returning the full
        `points_total` from held back to available points".

        Design: Difficulty/non_linear_state_machine/redemption_parallel_fulfillment_escrow
        """
        ctx = setup_employee_with_grant(2000)
        employee = ctx["employee"]
        _, item = setup_catalog(item_overrides={
            "sku": "BAG", "name": "Bag", "point_cost": 1000, "cash_value_cents": 5000,
        })
        created = validate_success(api.create_redemption_order(
            create_redemption_order_payload(item["id"], idempotency_key="nl2-r1"),
            make_employee_headers(employee["id"]),
        ), 201)
        assert created["fulfillment_status"] == "PENDING_SUBMISSION"
        assert created["escrow_status"] == "HELD"

        submitted = validate_success(api.submit_redemption_order(
            created["id"], VOPS
        ), 200)
        assert submitted["fulfillment_status"] == "SUBMITTED"
        assert submitted["escrow_status"] == "HELD"

        cancelled = validate_success(api.cancel_redemption_order(
            created["id"], make_employee_headers(employee["id"])
        ), 200)
        assert cancelled["fulfillment_status"] == "CANCELLED"
        assert cancelled["escrow_status"] == "REFUNDED"

        balance = validate_success(api.get_employee(employee["id"], hr_admin_headers), 200)
        assert balance["available_points"] == 2000
        assert balance["held_points"] == 0

    def test_escrow_stays_held_until_delivery_or_cancellation(
        self, api, hr_admin_headers
    ):
        """PRD §3.5: "Delivery is the settlement point, and in one logical
        step it: flips `escrow_status` from `HELD` to `SETTLED`".

        Design: Difficulty/non_linear_state_machine/redemption_parallel_fulfillment_escrow
        """
        ctx = setup_employee_with_grant(2000)
        _, item = setup_catalog(item_overrides={
            "sku": "BAG2", "name": "Bag2", "point_cost": 1000, "cash_value_cents": 5000,
        })
        delivered = deliver_redemption_order(
            item["id"], ctx["employee"], idempotency_key="nl2b-r1"
        )
        assert delivered["fulfillment_status"] == "DELIVERED"
        assert delivered["escrow_status"] == "SETTLED"
        balance = validate_success(
            api.get_employee(ctx["employee"]["id"], hr_admin_headers), 200
        )
        assert balance["held_points"] == 0


class TestPointsConservation:
    def test_redeem_then_cancel_conserves_total_point_stock(
        self, api, hr_admin_headers
    ):
        """PRD §2.9: "Employee balances are derived from this journal, never
        stored as independent truths. `available_points` is the spendable sum
        of ledger movements and may go negative when a clawback reaches points
        already spent; `held_points` is the points escrowed by open redemption
        orders".

        Design: Difficulty/compensating_invariant/redeem_then_cancel_points_conservation
        """
        ctx = setup_employee_with_grant(3000)
        employee = ctx["employee"]
        _, item = setup_catalog(item_overrides={
            "sku": "BAG3", "name": "Bag", "point_cost": 1000, "cash_value_cents": 5000,
        })
        order = validate_success(api.create_redemption_order(
            create_redemption_order_payload(item["id"], idempotency_key="ci1-r1"),
            make_employee_headers(employee["id"]),
        ), 201)

        mid = validate_success(api.get_employee(employee["id"], hr_admin_headers), 200)
        assert mid["available_points"] == 2000
        assert mid["held_points"] == 1000
        assert mid["available_points"] + mid["held_points"] == 3000

        get_success_data(api.cancel_redemption_order(
            order["id"], make_employee_headers(employee["id"])
        ))
        end = validate_success(api.get_employee(employee["id"], hr_admin_headers), 200)
        assert end["available_points"] == 3000
        assert end["held_points"] == 0

    def test_ledger_nets_to_original_grant_after_cancel(
        self, api, hr_admin_headers
    ):
        """PRD §2.9: "Direction conventions are fixed: a `HOLD` moves points
        from available to held; `SETTLE_REDEEM` and `RESTOCKING_FEE` move
        points out of held into spent; `CLAWBACK` and `EXPIRY` debit available
        points; grants and refunds credit available points."

        Design: Difficulty/compensating_invariant/redeem_then_cancel_points_conservation
        """
        ctx = setup_employee_with_grant(3000)
        employee = ctx["employee"]
        _, item = setup_catalog(item_overrides={
            "sku": "BAG4", "name": "Bag", "point_cost": 1000, "cash_value_cents": 5000,
        })
        order = validate_success(api.create_redemption_order(
            create_redemption_order_payload(item["id"], idempotency_key="ci1b-r1"),
            make_employee_headers(employee["id"]),
        ), 201)
        get_success_data(api.cancel_redemption_order(
            order["id"], make_employee_headers(employee["id"])
        ))

        entries, _ = validate_paginated(api.list_ledger_entries(
            employee["id"], hr_admin_headers
        ))
        by_type = [(e["entry_type"], e["points"]) for e in entries]
        assert ("GRANT_NOMINATION", 3000) in by_type
        assert ("HOLD", -1000) in by_type
        assert ("REFUND", 1000) in by_type
        fresh = validate_success(api.get_employee(employee["id"], hr_admin_headers), 200)
        assert_employee_ledger_reconciles(fresh, entries)


class TestVendorShipDateCapacity:
    def test_third_submit_rolls_to_next_business_day_at_capacity(
        self, api, hr_admin_headers, vendor_ops_headers
    ):
        """PRD §3.5: "While the number of that vendor's orders in `SUBMITTED`
        or `SHIPPED` already assigned to the candidate date reaches the
        vendor's `daily_ship_capacity`, the candidate rolls forward to the next
        business day; each calendar day is a capacity bucket, with no adjacency
        or gap treatment."

        Design: Difficulty/boundary_precision_check/vendor_capacity_rollover
        """
        get_success_data(api.set_clock("2026-08-03T00:00:00Z", hr_admin_headers))  # Monday
        ctx = setup_employee_with_grant(10000)
        employee = ctx["employee"]
        _, item = setup_catalog(
            vendor_overrides={"daily_ship_capacity": 2, "lead_time_business_days": 1},
            item_overrides={"sku": "MUG", "name": "Mug"},
        )
        orders = [
            validate_success(api.create_redemption_order(
                create_redemption_order_payload(item["id"], idempotency_key=f"bp3-r{i}"),
                make_employee_headers(employee["id"]),
            ), 201)
            for i in (1, 2, 3)
        ]
        ship_dates = [
            validate_success(api.submit_redemption_order(o["id"], vendor_ops_headers), 200)["ship_date"]
            for o in orders
        ]
        # Lead 1 business day from Monday 2026-08-03 -> Tuesday 2026-08-04;
        # capacity 2 fills that bucket, so the third rolls to 2026-08-05.
        assert ship_dates[0] == "2026-08-04"
        assert ship_dates[1] == "2026-08-04"
        assert ship_dates[2] == "2026-08-05"

    def test_shipped_orders_still_count_toward_the_capacity_bucket(
        self, api, hr_admin_headers, vendor_ops_headers
    ):
        """PRD §3.5: "While the number of that vendor's orders in `SUBMITTED`
        or `SHIPPED` already assigned to the candidate date reaches the
        vendor's `daily_ship_capacity`, the candidate rolls forward to the
        next business day".

        Design: Difficulty/boundary_precision_check/vendor_capacity_rollover
        """
        get_success_data(api.set_clock("2026-08-03T00:00:00Z", hr_admin_headers))  # Monday
        ctx = setup_employee_with_grant(10000)
        employee = ctx["employee"]
        _, item = setup_catalog(
            vendor_overrides={"daily_ship_capacity": 2, "lead_time_business_days": 1},
            item_overrides={"sku": "CAP2", "name": "CapTest"},
        )
        orders = [
            validate_success(api.create_redemption_order(
                create_redemption_order_payload(item["id"], idempotency_key=f"bp3b-r{i}"),
                make_employee_headers(employee["id"]),
            ), 201)
            for i in (1, 2, 3)
        ]
        first = validate_success(
            api.submit_redemption_order(orders[0]["id"], vendor_ops_headers), 200
        )
        # Move the first order to SHIPPED: it still occupies the bucket.
        get_success_data(api.mark_redemption_order_shipped(orders[0]["id"], vendor_ops_headers))
        second = validate_success(
            api.submit_redemption_order(orders[1]["id"], vendor_ops_headers), 200
        )
        third = validate_success(
            api.submit_redemption_order(orders[2]["id"], vendor_ops_headers), 200
        )
        assert first["ship_date"] == "2026-08-04"
        assert second["ship_date"] == "2026-08-04"
        assert third["ship_date"] == "2026-08-05"

    def test_weekend_skipped_and_other_vendor_bucket_unaffected(
        self, api, hr_admin_headers, vendor_ops_headers
    ):
        """PRD §3.5: "The selector starts from the candidate date obtained by
        adding the vendor's `lead_time_business_days` business days — Monday
        through Friday, skipping weekends — to the logical today."
        PRD §3.5: "each calendar day is a capacity bucket, with no adjacency or
        gap treatment."

        Design: Difficulty/resource_temporal_overlap/vendor_ship_date_aggregate_capacity
        """
        get_success_data(api.set_clock("2026-08-07T00:00:00Z", hr_admin_headers))  # Friday
        ctx = setup_employee_with_grant(10000)
        employee = ctx["employee"]
        v1 = create_vendor(name="VendOne", vendor_code="V1", daily_ship_capacity=1,
                           lead_time_business_days=1)
        v2 = create_vendor(name="VendTwo", vendor_code="V2", daily_ship_capacity=5,
                           lead_time_business_days=1)
        item1 = create_catalog_item(v1["id"], sku="A1", name="ItemA")
        item2 = create_catalog_item(v2["id"], sku="B1", name="ItemB")
        o1 = validate_success(api.create_redemption_order(
            create_redemption_order_payload(item1["id"], idempotency_key="to2-r1"),
            make_employee_headers(employee["id"]),), 201)
        o2 = validate_success(api.create_redemption_order(
            create_redemption_order_payload(item1["id"], idempotency_key="to2-r2"),
            make_employee_headers(employee["id"]),), 201)
        o3 = validate_success(api.create_redemption_order(
            create_redemption_order_payload(item2["id"], idempotency_key="to2-r3"),
            make_employee_headers(employee["id"]),), 201)

        s1 = validate_success(api.submit_redemption_order(o1["id"], vendor_ops_headers), 200)
        s2 = validate_success(api.submit_redemption_order(o2["id"], vendor_ops_headers), 200)
        s3 = validate_success(api.submit_redemption_order(o3["id"], vendor_ops_headers), 200)
        # Friday + 1 business day skips the weekend -> Monday 2026-08-10.
        assert s1["ship_date"] == "2026-08-10"
        # V1's Monday bucket (capacity 1) is full -> rolls to Tuesday.
        assert s2["ship_date"] == "2026-08-11"
        # V2's Monday bucket is independent and still free.
        assert s3["ship_date"] == "2026-08-10"

    def test_cancelled_submitted_order_frees_the_capacity_slot(
        self, api, hr_admin_headers, vendor_ops_headers
    ):
        """PRD §3.5: "Cancellation lands the order in `CANCELLED` with escrow
        `REFUNDED`, writes a `REFUND` ledger entry returning the full
        `points_total` from held back to available points, restores the
        catalog item's inventory by `quantity` when the item is stocked, and
        frees the vendor's `ship_date` capacity slot when the order had been
        `SUBMITTED`."

        Design: Difficulty/resource_temporal_overlap/vendor_ship_date_aggregate_capacity
        """
        get_success_data(api.set_clock("2026-08-07T00:00:00Z", hr_admin_headers))  # Friday
        ctx = setup_employee_with_grant(10000)
        employee = ctx["employee"]
        _, item = setup_catalog(
            vendor_overrides={"daily_ship_capacity": 1, "lead_time_business_days": 1},
            item_overrides={"sku": "FREE", "name": "FreeSlot"},
        )
        first = validate_success(api.create_redemption_order(
            create_redemption_order_payload(item["id"], idempotency_key="to2b-r1"),
            make_employee_headers(employee["id"]),), 201)
        second = validate_success(api.create_redemption_order(
            create_redemption_order_payload(item["id"], idempotency_key="to2b-r2"),
            make_employee_headers(employee["id"]),), 201)

        s1 = validate_success(
            api.submit_redemption_order(first["id"], vendor_ops_headers), 200
        )
        assert s1["ship_date"] == "2026-08-10"  # Friday + 1 business day
        # Cancelling the SUBMITTED order frees its Monday slot, so the next
        # submit lands the same Monday rather than rolling to Tuesday.
        get_success_data(api.cancel_redemption_order(
            first["id"], make_employee_headers(employee["id"])
        ))
        s2 = validate_success(
            api.submit_redemption_order(second["id"], vendor_ops_headers), 200
        )
        assert s2["ship_date"] == "2026-08-10"

    def test_vendor_beyond_lookahead_rejects_first_submit(
        self, api, hr_admin_headers, vendor_ops_headers
    ):
        """PRD §3.5: "If the candidate lands beyond 45 calendar days from the
        logical today, submission is rejected with
        `ERR_VENDOR_CAPACITY_EXCEEDED`; a candidate exactly 45 days out is
        still assignable."

        Design: Corner/errors/vendor_capacity_exhausted_lookahead
        """
        ctx = setup_employee_with_grant(1000)
        _, item = setup_catalog(
            vendor_overrides={"name": "SlowCo", "vendor_code": "SLOW",
                              "daily_ship_capacity": 1, "lead_time_business_days": 40},
            item_overrides={"sku": "M", "name": "Mug"},
        )
        order = validate_success(api.create_redemption_order(
            create_redemption_order_payload(item["id"], idempotency_key="err-cap-r1"),
            make_employee_headers(ctx["employee"]["id"]),), 201)
        res = api.submit_redemption_order(order["id"], vendor_ops_headers)
        validate_error(res, ApiErrorId.ERR_VENDOR_CAPACITY_EXCEEDED)
        current = validate_success(
            api.get_redemption_order(order["id"], hr_admin_headers), 200
        )
        assert current["ship_date"] is None
        assert current["fulfillment_status"] == "PENDING_SUBMISSION"


class TestVendorSuspension:
    def test_suspended_vendor_blocks_submit_until_reactivated(
        self, api, hr_admin_headers, vendor_ops_headers
    ):
        """PRD §3.5: "An `HRAdmin` may suspend a vendor — only from `ACTIVE`,
        else `ERR_INVALID_STATE_TRANSITION` — which blocks two things while it
        lasts: submitting any of the vendor's `PENDING_SUBMISSION` orders, and
        creating new catalog items for it, both refused with
        `ERR_VENDOR_SUSPENDED`."

        Design: Corner/endpoints/vendor_suspended_blocks_submit
        """
        ctx = setup_employee_with_grant(1000)
        vendor, item = setup_catalog()
        order = validate_success(api.create_redemption_order(
            create_redemption_order_payload(item["id"], idempotency_key="ep-vs-r1"),
            make_employee_headers(ctx["employee"]["id"]),), 201)

        get_success_data(api.suspend_vendor(vendor["id"], hr_admin_headers))
        res = api.submit_redemption_order(order["id"], vendor_ops_headers)
        validate_error(res, ApiErrorId.ERR_VENDOR_SUSPENDED)

        get_success_data(api.reactivate_vendor(vendor["id"], hr_admin_headers))
        submitted = validate_success(
            api.submit_redemption_order(order["id"], vendor_ops_headers), 200
        )
        assert submitted["fulfillment_status"] == "SUBMITTED"
        # Default clock 2026-08-01 is a Saturday; 1 business day lead lands
        # on Monday 2026-08-03.
        assert submitted["ship_date"] == "2026-08-03"


class TestInvalidOrderTransitions:
    def test_mark_shipped_from_pending_submission_rejected(
        self, api, hr_admin_headers, vendor_ops_headers
    ):
        """PRD §3.5: "From `SUBMITTED`, a `VendorOps` operator marks the order
        `SHIPPED`; from `SHIPPED`, they mark it `DELIVERED` — anything else is
        `ERR_INVALID_STATE_TRANSITION`."

        Design: Corner/state_machines/mark_shipped_from_pending_returns_invalid_state
        """
        ctx = setup_employee_with_grant(1000)
        _, item = setup_catalog()
        order = validate_success(api.create_redemption_order(
            create_redemption_order_payload(item["id"], idempotency_key="sm-sh-r1"),
            make_employee_headers(ctx["employee"]["id"]),), 201)
        res = api.mark_redemption_order_shipped(order["id"], vendor_ops_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        current = validate_success(
            api.get_redemption_order(order["id"], hr_admin_headers), 200
        )
        assert current["ship_date"] is None
        assert current["fulfillment_status"] == "PENDING_SUBMISSION"

    def test_cancel_delivered_order_rejected(self, api, hr_admin_headers):
        """PRD §3.5: "From `PENDING_SUBMISSION` or `SUBMITTED` — and only those
        states — the owning employee, or an `HRAdmin`, may cancel".

        Design: Corner/state_machines/cancel_delivered_order_returns_invalid_state
        """
        ctx = setup_employee_with_grant(1000)
        _, item = setup_catalog()
        delivered = deliver_redemption_order(
            item["id"], ctx["employee"], idempotency_key="sm-cd-r1"
        )
        res = api.cancel_redemption_order(
            delivered["id"], make_employee_headers(ctx["employee"]["id"])
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        current = validate_success(
            api.get_redemption_order(delivered["id"], hr_admin_headers), 200
        )
        assert current["escrow_status"] == "SETTLED"


class TestReturnRules:
    def test_gift_card_return_rejected(self, api, hr_admin_headers):
        """PRD §3.5: "The owning employee requests a return within fourteen
        days of `delivered_at`; gift cards are never returnable, and either
        violation is `ERR_RETURN_NOT_ALLOWED`."

        Design: Corner/validations/gift_card_return_rejected
        """
        ctx = setup_employee_with_grant(1000)
        employee = ctx["employee"]
        vendor = create_vendor(supported_categories=["GIFTCARD"])
        item = create_catalog_item(
            vendor["id"], sku="GC", name="Gift Card", category="GIFTCARD",
            point_cost=500, cash_value_cents=2500, taxable_class="GIFT_CARD",
        )
        delivered = deliver_redemption_order(
            item["id"], employee, idempotency_key="val-gc-r1"
        )
        res = api.request_redemption_order_return(
            delivered["id"], make_employee_headers(employee["id"]),
            reason="changed mind",
        )
        validate_error(res, ApiErrorId.ERR_RETURN_NOT_ALLOWED)

    def test_return_window_boundary_fourteen_days_inclusive(
        self, api, hr_admin_headers
    ):
        """PRD §3.5: "The owning employee requests a return within fourteen
        days of `delivered_at`; gift cards are never returnable, and either
        violation is `ERR_RETURN_NOT_ALLOWED`."

        Design: Corner/state_machines/return_window_boundary_14_days
        """
        get_success_data(api.set_clock("2026-08-03T00:00:00Z", hr_admin_headers))
        ctx = setup_employee_with_grant(2000)
        employee = ctx["employee"]
        _, item = setup_catalog()
        first = deliver_redemption_order(item["id"], employee, idempotency_key="sm-rw-r1")
        second = deliver_redemption_order(item["id"], employee, idempotency_key="sm-rw-r2")

        # Exactly 14 days after the 2026-08-03 delivery: still allowed.
        get_success_data(api.set_clock("2026-08-17T00:00:00Z", hr_admin_headers))
        ok = validate_success(api.request_redemption_order_return(
            first["id"], make_employee_headers(employee["id"]),
            reason="exactly 14 days",
        ), 200)
        assert ok["fulfillment_status"] == "RETURN_REQUESTED"

        # Past the window: rejected.
        get_success_data(api.set_clock("2026-08-18T00:00:01Z", hr_admin_headers))
        res = api.request_redemption_order_return(
            second["id"], make_employee_headers(employee["id"]), reason="too late",
        )
        validate_error(res, ApiErrorId.ERR_RETURN_NOT_ALLOWED)


class TestRedemptionAnomalyFlag:
    def test_large_order_succeeds_and_raises_redemption_anomaly_flag(
        self, api, hr_admin_headers
    ):
        """PRD §3.5: "a single order whose `points_total` exceeds 50000
        auto-creates an `OPEN` abuse flag with `rule_code` `REDEMPTION_ANOMALY`
        — but the order still succeeds."

        Design: Corner/cross_cutting_layers/redemption_anomaly_flag_auto_created
        """
        ctx = setup_employee_with_grant(
            60000, program_overrides={"max_points_per_nomination": 100000},
        )
        employee = ctx["employee"]
        _, item = setup_catalog(item_overrides={
            "sku": "LUXE", "name": "Luxe", "point_cost": 60000,
            "cash_value_cents": 300000,
        })
        order = validate_success(api.create_redemption_order(
            create_redemption_order_payload(item["id"], idempotency_key="xcut-an-r1"),
            make_employee_headers(employee["id"]),), 201)
        assert order["fulfillment_status"] == "PENDING_SUBMISSION"

        flags, meta = validate_paginated(api.list_abuse_flags(
            hr_admin_headers,
            params={"employee_id": employee["id"], "rule_code": "REDEMPTION_ANOMALY"},
        ))
        assert meta["total_count"] == 1
        assert flags[0]["status"] == "OPEN"
