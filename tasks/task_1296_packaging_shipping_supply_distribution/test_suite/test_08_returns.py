"""Returns: creation gating, stock-vs-custom refund variants, per-line rounding
order, the 30-day window, line eligibility, and cumulative quantity limits."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_line,
    assert_return,
    complete_print_job,
    create_custom_product,
    create_draft_order,
    create_inventory,
    create_stock_product,
    find_job_for_line,
    make_buyer_headers,
    request_return,
    set_clock,
    setup_shipped_custom_order,
    setup_shipped_stock_order,
    setup_submitted_stock_order,
    setup_warehouse_and_account,
    ship_order,
    submit_order,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
OPS = TEST_USERS["warehouse_ops_headers"]
SERVICE = TEST_USERS["customer_service_headers"]


class TestReturnCreationGate:
    def test_return_against_unshipped_order_rejected(self, api):
        """PRD section 3.8: "The referenced order must be `SHIPPED`; requesting
        a return against an order in any other state is rejected with
        `ERR_INVALID_STATE`."

        Design: Difficulty/cross_entity_state_dependency/return_creation_gated_by_order_shipped_state
        """
        ctx = setup_submitted_stock_order(qty=2, on_hand=100)  # STOCK_RESERVED, not shipped
        resp = api.create_return({
            "order_id": ctx["order"]["id"], "return_type": "STOCK",
            "reason_code": "CHANGED_MIND",
            "lines": [{"order_line_id": ctx["line"]["id"], "qty": 1}],
        }, ctx["buyer_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_return_against_shipped_order_accepted(self, api, warehouse_ops_headers):
        """PRD section 3.8: "The referenced order must be `SHIPPED`; requesting
        a return against an order in any other state is rejected with
        `ERR_INVALID_STATE`."
        PRD section 3.8: "A new return is stamped `requested_at` from the
        logical clock and starts `REQUESTED`."

        Design: Difficulty/cross_entity_state_dependency/return_creation_gated_by_order_shipped_state
        """
        ctx = setup_submitted_stock_order(qty=2, on_hand=100)
        validate_error(api.create_return({
            "order_id": ctx["order"]["id"], "return_type": "STOCK",
            "reason_code": "CHANGED_MIND",
            "lines": [{"order_line_id": ctx["line"]["id"], "qty": 1}],
        }, ctx["buyer_headers"]), ApiErrorId.ERR_INVALID_STATE)

        validate_success(api.ship_order(ctx["order"]["id"], warehouse_ops_headers))
        ret = validate_success(api.create_return({
            "order_id": ctx["order"]["id"], "return_type": "STOCK",
            "reason_code": "CHANGED_MIND",
            "lines": [{"order_line_id": ctx["line"]["id"], "qty": 1}],
        }, ctx["buyer_headers"]), expected_status=201)
        assert_return(ret)
        assert ret["status"] == "REQUESTED"


class TestStockVsCustomRefund:
    """Identical shape (qty 10 at a 1000-cent-class unit price): STOCK refunds
    100%; CUSTOM refunds 85% of the surcharged 1150-cent unit."""

    def test_stock_return_refunds_full_amount_no_fee(self, api, customer_service_headers):
        """PRD section 3.8: "Approval computes the financials: per return line,
        the credit is the returned quantity times the order line's
        `unit_price_cents`, scaled by one minus the restocking percentage —
        fifteen percent for `CUSTOM` returns, zero for `STOCK` — rounded
        half-up to a whole cent per line; `refund_cents` is the sum of those
        per-line credits, and `restock_fee_cents` is the sum over lines of the
        returned quantity times the unit price times the restocking percentage,
        likewise rounded half-up per line before summing."

        Design: Difficulty/dual_variant_calc/return_refund_stock_full_vs_custom_restock_fee
        """
        ctx = setup_shipped_stock_order(qty=10, on_hand=100)
        ret = request_return(ctx["order"]["id"], ctx["account"]["id"],
                             [{"order_line_id": ctx["line"]["id"], "qty": 10}],
                             return_type="STOCK", reason_code="WRONG_ITEM")
        approved = validate_success(api.approve_return(ret["id"], customer_service_headers))
        assert_return(approved)
        assert approved["refund_cents"] == 10000        # 10 x 1000 x (1 - 0)
        assert approved["restock_fee_cents"] == 0

    def test_custom_return_refunds_85pct_with_15pct_fee(self, api, customer_service_headers):
        """PRD section 3.8: "Approval computes the financials: per return line,
        the credit is the returned quantity times the order line's
        `unit_price_cents`, scaled by one minus the restocking percentage —
        fifteen percent for `CUSTOM` returns, zero for `STOCK` — rounded
        half-up to a whole cent per line; `refund_cents` is the sum of those
        per-line credits, and `restock_fee_cents` is the sum over lines of the
        returned quantity times the unit price times the restocking percentage,
        likewise rounded half-up per line before summing."

        Design: Difficulty/dual_variant_calc/return_refund_stock_full_vs_custom_restock_fee
        """
        ctx = setup_shipped_custom_order(qty=10, actual_qty=10, base_price_cents=1000,
                                         lead_time_days=3, sku="BX-C1",
                                         weight_lbs_per_unit=5)
        ret = request_return(ctx["order"]["id"], ctx["account"]["id"],
                             [{"order_line_id": ctx["line"]["id"], "qty": 10}],
                             return_type="CUSTOM", reason_code="PRINT_DEFECT")
        approved = validate_success(api.approve_return(ret["id"], customer_service_headers))
        # Unit price is the surcharged 1150: credit 10 x 1150 x 0.85 = 9775.
        assert approved["refund_cents"] == 9775
        assert approved["restock_fee_cents"] == 1725    # 10 x 1150 x 0.15
        assert approved["refund_cents"] + approved["restock_fee_cents"] == 11500


class TestPerLineRoundThenSum:
    """Two custom lines of qty 1 at unit 331 (ceil(287 x 1.15)): the pinned
    per-line rounding gives 2 x 281 = 562, one cent below sum-then-round 563."""

    def test_refund_rounds_per_line_before_summing(self, api, customer_service_headers):
        """PRD section 3.8: "The pinned order is round-per-line-then-sum, which
        differs by design from summing first and rounding once."
        PRD section 3.8: "`refund_cents` is the sum of those per-line credits"

        Design: Difficulty/combinatorial_formula/return_refund_per_line_round_then_sum
        """
        ctx = self._setup_two_line_custom_return(api)
        approved = validate_success(api.approve_return(ctx["return"]["id"], customer_service_headers))
        # round_half_up(331 x 0.85) = 281 per line, summed AFTER rounding.
        assert approved["refund_cents"] == 562

    def test_restock_fee_rounds_per_line_before_summing(self, api, customer_service_headers):
        """PRD section 3.8: "The pinned order is round-per-line-then-sum, which
        differs by design from summing first and rounding once."
        PRD section 3.8: "`restock_fee_cents` is the sum over lines of the
        returned quantity times the unit price times the restocking percentage,
        likewise rounded half-up per line before summing."

        Design: Difficulty/combinatorial_formula/return_refund_per_line_round_then_sum
        """
        ctx = self._setup_two_line_custom_return(api)
        approved = validate_success(api.approve_return(ctx["return"]["id"], customer_service_headers))
        # round_half_up(331 x 0.15) = 50 per line; refund + fee recompose the gross.
        assert approved["restock_fee_cents"] == 100
        assert approved["refund_cents"] + approved["restock_fee_cents"] == 662

    def _setup_two_line_custom_return(self, api):
        wh, acct = setup_warehouse_and_account()
        prod = create_custom_product(sku="LB-C1", name="Custom Label", category="LABELS",
                                     base_price_cents=287, lead_time_days=2, pallet_qty=100,
                                     weight_lbs_per_unit=1)
        set_clock("2026-08-03T10:00:00Z")
        order = create_draft_order(acct["id"], ship_zone=5)
        l1 = add_line(order["id"], acct["id"], prod["id"], 1,
                      print_artwork_ref="art-a", over_under_tolerance_pct=10)
        l2 = add_line(order["id"], acct["id"], prod["id"], 1,
                      print_artwork_ref="art-b", over_under_tolerance_pct=10)
        submit_order(order["id"], acct["id"])
        complete_print_job(find_job_for_line(l1["id"])["id"], 1)
        complete_print_job(find_job_for_line(l2["id"])["id"], 1)
        ship_order(order["id"])
        ret = request_return(order["id"], acct["id"],
                             [{"order_line_id": l1["id"], "qty": 1},
                              {"order_line_id": l2["id"], "qty": 1}],
                             return_type="CUSTOM", reason_code="PRINT_DEFECT")
        return {"account": acct, "order": order, "lines": (l1, l2), "return": ret}


class TestReturnTerminalLockdown:
    def test_rejected_return_rejects_approve_and_receive(self, api, customer_service_headers,
                                                         warehouse_ops_headers):
        """PRD section 3.8: "Rejection, with an optional `reason`, moves the
        return to `REJECTED`, a terminal state."
        PRD section 2.9: "Next, the requested transition must exist from the
        target resource's current state, including terminal-state lockdown
        (`ERR_INVALID_STATE`)."

        Design: Corner/state_machines/return_terminal_rejected_lockdown
        """
        ctx = setup_shipped_stock_order(qty=2, on_hand=100)
        ret = request_return(ctx["order"]["id"], ctx["account"]["id"],
                             [{"order_line_id": ctx["line"]["id"], "qty": 1}])
        rejected = validate_success(api.reject_return(ret["id"], {"reason": "outside policy"},
                                                      customer_service_headers))
        assert rejected["status"] == "REJECTED"

        validate_error(api.approve_return(ret["id"], customer_service_headers),
                       ApiErrorId.ERR_INVALID_STATE)
        validate_error(api.receive_return(ret["id"], warehouse_ops_headers),
                       ApiErrorId.ERR_INVALID_STATE)


class TestReturnWindow:
    def _setup_two_shipped_returns(self, api):
        wh, acct = setup_warehouse_and_account()
        prod = create_stock_product(sku="R-1", base_price_cents=100, pallet_qty=10,
                                    weight_lbs_per_unit=1)
        create_inventory(prod["id"], wh["id"], 100)
        set_clock("2026-08-03T10:00:00Z")
        returns = []
        for _ in range(2):
            order = create_draft_order(acct["id"], ship_zone=5)
            line = add_line(order["id"], acct["id"], prod["id"], 1)
            submit_order(order["id"], acct["id"])
            ship_order(order["id"])
            returns.append(request_return(order["id"], acct["id"],
                                          [{"order_line_id": line["id"], "qty": 1}]))
        return returns

    def test_approve_within_30_day_window_passes_and_after_expires(self, api,
                                                                   customer_service_headers):
        """PRD section 3.8: "The request must be no older than thirty calendar
        days — `requested_at` must sit at or after the instant thirty days
        before the current clock — or approval fails with
        `ERR_RETURN_WINDOW_EXPIRED` (HTTP 422)."

        Design: Corner/validations/error_return_window_expired_after_30_days
        """
        r1, r2 = self._setup_two_shipped_returns(api)

        set_clock("2026-09-01T10:00:00Z")  # 29 days after the 2026-08-03 request
        approved = validate_success(api.approve_return(r1["id"], customer_service_headers))
        assert approved["status"] == "APPROVED"

        set_clock("2026-09-03T10:00:01Z")  # 31 days (and one second) after
        resp = api.approve_return(r2["id"], customer_service_headers)
        validate_error(resp, ApiErrorId.ERR_RETURN_WINDOW_EXPIRED)


class TestMixedReturnEligibility:
    def _setup_mixed_shipped_order(self, api):
        wh, acct = setup_warehouse_and_account()
        prod_s = create_stock_product(sku="S-1", base_price_cents=100, pallet_qty=10,
                                      weight_lbs_per_unit=1)
        prod_c = create_custom_product(sku="S-2", category="LABELS", base_price_cents=100,
                                       lead_time_days=2, pallet_qty=10,
                                       weight_lbs_per_unit=1)
        create_inventory(prod_s["id"], wh["id"], 100)
        set_clock("2026-08-03T10:00:00Z")
        order = create_draft_order(acct["id"], ship_zone=5)
        l_s = add_line(order["id"], acct["id"], prod_s["id"], 1)
        l_c = add_line(order["id"], acct["id"], prod_c["id"], 1,
                       print_artwork_ref="art-s", over_under_tolerance_pct=10)
        submitted = submit_order(order["id"], acct["id"])
        assert submitted["status"] == "CUSTOM_PRODUCTION"
        complete_print_job(find_job_for_line(l_c["id"])["id"], 1)
        ship_order(order["id"])
        return acct, order, l_s, l_c

    def test_stock_return_with_custom_line_and_custom_return_with_stock_line_rejected(self, api):
        """PRD section 3.8: "Type eligibility is enforced both at request time
        and again at approval: a `CUSTOM` return may reference only
        custom-print lines and a `STOCK` return only stock lines — any mismatch
        is `ERR_CUSTOM_NOT_RETURNABLE` (HTTP 422)."

        Design: Corner/validations/error_custom_not_returnable_mixed_return_lines
        """
        acct, order, l_s, l_c = self._setup_mixed_shipped_order(api)
        stock_with_custom = api.create_return({
            "order_id": order["id"], "return_type": "STOCK", "reason_code": "X",
            "lines": [{"order_line_id": l_c["id"], "qty": 1}],
        }, make_buyer_headers(acct["id"]))
        validate_error(stock_with_custom, ApiErrorId.ERR_CUSTOM_NOT_RETURNABLE)

        custom_with_stock = api.create_return({
            "order_id": order["id"], "return_type": "CUSTOM", "reason_code": "X",
            "lines": [{"order_line_id": l_s["id"], "qty": 1}],
        }, make_buyer_headers(acct["id"]))
        validate_error(custom_with_stock, ApiErrorId.ERR_CUSTOM_NOT_RETURNABLE)


class TestReturnQtyExceeded:
    def test_cumulative_return_qty_capped_at_shipped(self, api, customer_service_headers):
        """PRD section 3.8: "Each requested `qty` must be at least one and may
        not exceed the order line's `shipped_qty` minus the quantities already
        carried on that line's prior non-`REJECTED` returns, or the request
        fails with `ERR_RETURN_QTY_EXCEEDED` (HTTP 422)."

        Design: Corner/validations/error_return_qty_exceeded_across_multiple_returns
        """
        ctx = setup_shipped_stock_order(qty=3, on_hand=100)
        first = request_return(ctx["order"]["id"], ctx["account"]["id"],
                               [{"order_line_id": ctx["line"]["id"], "qty": 2}],
                               reason_code="DAMAGED")
        validate_success(api.approve_return(first["id"], customer_service_headers))

        # Shipped 3, already returning 2 -> only 1 remains.
        over = api.create_return({
            "order_id": ctx["order"]["id"], "return_type": "STOCK", "reason_code": "DAMAGED",
            "lines": [{"order_line_id": ctx["line"]["id"], "qty": 2}],
        }, ctx["buyer_headers"])
        validate_error(over, ApiErrorId.ERR_RETURN_QTY_EXCEEDED)

        exact = validate_success(api.create_return({
            "order_id": ctx["order"]["id"], "return_type": "STOCK", "reason_code": "DAMAGED",
            "lines": [{"order_line_id": ctx["line"]["id"], "qty": 1}],
        }, ctx["buyer_headers"]), expected_status=201)
        assert_return(exact)
        assert exact["status"] == "REQUESTED"
