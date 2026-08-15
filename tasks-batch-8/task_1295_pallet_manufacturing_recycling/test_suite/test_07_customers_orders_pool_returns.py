"""Customers, order pricing, pool returns, and the credit ledger."""
import pytest

from test_helpers import (
    SALES,
    ApiErrorId,
    add_order_line,
    api_client,
    create_active_spec,
    create_customer,
    create_order,
    get_customer,
    get_order,
    grade_pool_return,
    list_order_lines,
    log_pool_return,
    publish_seasonal_index,
    setup_customer_with_credit,
    setup_delivered_customer,
    setup_sellable_world,
    validate_error,
    validate_success,
)


class TestCustomerClose:

    def test_close_customer_with_draft_order_rejected(self):
        """PRD §3.6: "Closing a customer requires `ACTIVE` (else
        `ERR_CUSTOMER_NOT_ACTIVE`), zero pool exposure — `pool_units_outstanding`
        must be zero, else `ERR_POOL_UNITS_OUTSTANDING` — and no live orders:
        any sales order with `fulfillment_status` `DRAFT`, `CONFIRMED`,
        `ALLOCATED`, or `SHIPPED` blocks closure with `ERR_OPEN_ORDERS_EXIST`."

        Design: Corner/state_machines/customer_close_blocked_by_open_orders
        """
        customer = create_customer("OpenOrderCust")
        spec = create_active_spec()
        create_order(customer["id"], spec["id"], 1, "NEW")
        resp = api_client.close_customer(customer["id"], SALES)
        validate_error(resp, ApiErrorId.ERR_OPEN_ORDERS_EXIST)
        assert resp.status_code == 409
        after = get_customer(customer["id"])
        assert after["status"] == "ACTIVE"

    def test_close_customer_with_pool_units_rejected(self):
        """PRD §3.6: "Closing a customer requires `ACTIVE` (else
        `ERR_CUSTOMER_NOT_ACTIVE`), zero pool exposure — `pool_units_outstanding`
        must be zero, else `ERR_POOL_UNITS_OUTSTANDING` — and no live orders:
        any sales order with `fulfillment_status` `DRAFT`, `CONFIRMED`,
        `ALLOCATED`, or `SHIPPED` blocks closure with `ERR_OPEN_ORDERS_EXIST`."

        Design: Corner/errors/error_pool_units_outstanding_on_close
        """
        spec, _lot, cust = setup_sellable_world("OutStand", lot_quantity=100)
        customer, order = setup_delivered_customer(
            "OutStand", spec["id"], 1, customer_id=cust["id"])
        # The order is DELIVERED (terminal); pool units are the sole blocker.
        assert customer["pool_units_outstanding"] == 1
        resp = api_client.close_customer(customer["id"], SALES)
        validate_error(resp, ApiErrorId.ERR_POOL_UNITS_OUTSTANDING)
        assert resp.status_code == 409
        after = get_customer(customer["id"])
        assert after["status"] == "ACTIVE"


class TestCreditStandingGate:

    def test_confirm_for_suspended_customer_rejected(self):
        """PRD §3.6: "The confirm action requires the order to be `DRAFT` (else
        `ERR_ORDER_NOT_DRAFT`), at least one `OPEN` line (else
        `ERR_ORDER_EMPTY`), and an `ACTIVE` customer off credit hold (else
        `ERR_CUSTOMER_CREDIT_HOLD`)"
        PRD §3.6: "Suspension by a `SalesRep` moves `ACTIVE` to `SUSPENDED`
        (requiring `ACTIVE`, else `ERR_CUSTOMER_NOT_ACTIVE`) and sets
        `credit_hold` true, and while suspended, new order creation for the
        customer is rejected."

        Design: Corner/validations/order_confirm_on_suspended_customer_rejected
        """
        customer = create_customer("HoldCust")
        spec = create_active_spec()
        order = create_order(customer["id"], spec["id"], 1, "NEW")
        suspend = api_client.suspend_customer(customer["id"], SALES)
        validate_success(suspend)
        resp = api_client.confirm_order(
            order["id"], {"expected_order_version": order["version"]}, SALES)
        validate_error(resp, ApiErrorId.ERR_CUSTOMER_CREDIT_HOLD)
        assert resp.status_code == 422
        after = get_order(order["id"])
        assert after["fulfillment_status"] == "DRAFT", (
            f"rejected confirm must leave the order DRAFT, "
            f"got {after['fulfillment_status']}"
        )


class TestPoolReturns:

    def test_disputed_return_cannot_be_credited(self):
        """PRD §3.7: "A return still `LOGGED` may instead be disputed by a
        `SalesRep`, moving it to terminal `DISPUTED` (else
        `ERR_RETURN_NOT_LOGGED`); `CREDITED` and `DISPUTED` are both terminal."
        PRD §3.7: "Crediting is a `SalesRep` act requiring `GRADED` status
        (else `ERR_RETURN_NOT_GRADED`)"

        Design: Corner/state_machines/pool_return_dispute_terminal
        """
        customer = create_customer("DisputeCust")
        ret = log_pool_return(customer["id"], 2, "B")
        disputed = validate_success(api_client.dispute_pool_return(
            ret["id"], SALES))
        assert disputed["status"] == "DISPUTED"
        resp = api_client.credit_pool_return(ret["id"], SALES)
        validate_error(resp, ApiErrorId.ERR_RETURN_NOT_GRADED)
        assert resp.status_code == 409

    def test_credit_return_exceeding_outstanding_rejected(self):
        """PRD §3.7: "Crediting is a `SalesRep` act requiring `GRADED` status
        (else `ERR_RETURN_NOT_GRADED`) and a pool-solvency check: the
        customer's `pool_units_outstanding` must be at least the
        `returned_count`, else `ERR_RETURN_EXCEEDS_OUTSTANDING`."

        Design: Corner/validations/return_exceeds_outstanding_rejected
        """
        customer = create_customer("OverReturn")
        ret = log_pool_return(customer["id"], 2, "A")
        grade_pool_return(ret["id"], "A")
        resp = api_client.credit_pool_return(ret["id"], SALES)
        validate_error(resp, ApiErrorId.ERR_RETURN_EXCEEDS_OUTSTANDING)
        assert resp.status_code == 422
        cust = get_customer(customer["id"])
        assert cust["pool_credit_balance_cents"] == 0
        after = validate_success(api_client.get_pool_return(ret["id"], SALES))
        assert after["status"] == "GRADED", (
            f"rejected credit must leave the return GRADED, got {after['status']}"
        )

    def test_pool_credit_b_tier_lookup(self):
        """PRD §3.7: "Grading resolves the per-unit credit from the pool credit
        tier table — an exact enum lookup with no interpolation: seven hundred
        cents per `A` unit, three hundred fifty per `B` unit, zero for `SCRAP`
        — into `credit_per_unit_cents`, and computes `total_credit_cents` as
        `returned_count` times that per-unit figure."
        PRD §3.7: "Crediting posts the ledger in one motion — the customer's
        `pool_credit_balance_cents` grows by `total_credit_cents` and
        `pool_units_outstanding` shrinks by `returned_count`"

        Design: Corner/calculations/pool_credit_tier_exact_enum_lookup
        """
        spec, _lot, cust = setup_sellable_world("TierCust", lot_quantity=100)
        customer, _order = setup_delivered_customer(
            "TierCust", spec["id"], 3, customer_id=cust["id"])
        ret = log_pool_return(customer["id"], 3, "B")
        graded = grade_pool_return(ret["id"], "B")
        assert graded["credit_per_unit_cents"] == 350, (
            f"B tier is 350 cents per unit, got {graded['credit_per_unit_cents']}"
        )
        assert graded["total_credit_cents"] == 1050, (
            f"3 * 350 = 1050, got {graded['total_credit_cents']}"
        )
        credited = validate_success(api_client.credit_pool_return(
            ret["id"], SALES))
        assert credited["status"] == "CREDITED"
        cust = get_customer(customer["id"])
        assert cust["pool_credit_balance_cents"] == 1050
        assert cust["pool_units_outstanding"] == 0


class TestParallelStatusDimensions:

    def _setup_credit_rich_customer(self, spec_id):
        """Customer with 2800 cents pool credit (4 A-grade units returned)."""
        customer, _ret = setup_customer_with_credit(
            spec_id, company_name="CreditRich", delivered_qty=5,
            return_count=4, return_grade="A")
        assert customer["pool_credit_balance_cents"] == 2800
        assert customer["pool_units_outstanding"] == 1
        return customer

    def test_full_credit_confirm_flips_payment_to_credit_settled(self):
        """PRD §3.6: "`pool_credit_applied_cents` is the lesser of the
        customer's `pool_credit_balance_cents` and the sum of `subtotal_cents`
        and `seasonal_adjustment_cents`, and the customer's
        `pool_credit_balance_cents` is debited by that same amount in ledger
        sync."
        PRD §3.6: "The `total_cents` is the subtotal plus the seasonal
        adjustment minus the applied credit; when the total lands on zero, the
        payment axis flips straight to `CREDIT_SETTLED`, otherwise it remains
        `UNPAID`."

        Design: Difficulty/non_linear_state_machine/sales_order_parallel_payment_fulfillment_dimensions
        """
        spec, _lot, _c = setup_sellable_world(lot_quantity=500)
        customer = self._setup_credit_rich_customer(spec["id"])
        order = create_order(customer["id"], spec["id"], 1, "NEW")
        resp = api_client.confirm_order(
            order["id"], {"expected_order_version": order["version"]}, SALES)
        confirmed = validate_success(resp)
        assert confirmed["subtotal_cents"] == 1500
        assert confirmed["seasonal_adjustment_cents"] == 0
        assert confirmed["pool_credit_applied_cents"] == 1500, (
            "credit application is min(2800, 1500) = 1500"
        )
        assert confirmed["total_cents"] == 0
        assert confirmed["payment_status"] == "CREDIT_SETTLED", (
            f"zero total must settle by credit, got {confirmed['payment_status']}"
        )

    def test_payment_axis_terminal_while_fulfillment_mid_pipeline(self):
        """PRD §2.9: "A sales order has a `payment_status` (`UNPAID`, `PAID`,
        or `CREDIT_SETTLED`) and a `fulfillment_status` (`DRAFT`, `CONFIRMED`,
        `ALLOCATED`, `SHIPPED`, `DELIVERED`, or `CANCELLED`), and an action on
        one axis leaves the other untouched."
        PRD §3.6: "The `total_cents` is the subtotal plus the seasonal
        adjustment minus the applied credit; when the total lands on zero, the
        payment axis flips straight to `CREDIT_SETTLED`, otherwise it remains
        `UNPAID`."

        Design: Difficulty/non_linear_state_machine/sales_order_parallel_payment_fulfillment_dimensions
        """
        spec, _lot, _c = setup_sellable_world(lot_quantity=500)
        customer = self._setup_credit_rich_customer(spec["id"])
        order = create_order(customer["id"], spec["id"], 1, "NEW")
        confirmed = validate_success(api_client.confirm_order(
            order["id"], {"expected_order_version": order["version"]}, SALES))
        assert confirmed["payment_status"] == "CREDIT_SETTLED"
        assert confirmed["fulfillment_status"] == "CONFIRMED", (
            "payment reached a terminal state while fulfillment sits "
            "mid-pipeline: the axes evolve independently"
        )
        cust = get_customer(customer["id"])
        assert cust["pool_credit_balance_cents"] == 1300, (
            f"2800 - 1500 applied = 1300 remaining, "
            f"got {cust['pool_credit_balance_cents']}"
        )


class TestOrderPricing:

    def test_confirm_prices_per_line_then_sums(self):
        """PRD §3.6: "Confirmation computes each `OPEN` line's
        `extended_price_cents` as `quantity` times `unit_price_cents` rounded
        half-up to whole cents — per line first, then summed into
        `subtotal_cents`, never summed and then rounded."
        PRD §3.6: "Each line's `unit_price_cents` is stamped at creation from
        the grade price book — fifteen hundred cents for `NEW`, eleven hundred
        for `A`, eight hundred for `B`"

        Design: Difficulty/combinatorial_formula/order_pricing_per_line_rounding_then_sum
        """
        publish_seasonal_index()  # PEAK-2026-Q3 at 11000 bp
        spec = create_active_spec()
        customer = create_customer("RoundTripper")
        order = create_order(customer["id"], spec["id"], 10, "NEW")
        line2 = add_order_line(order["id"], spec["id"], 5, "A")
        resp = api_client.confirm_order(
            order["id"], {"expected_order_version": order["version"]}, SALES)
        confirmed = validate_success(resp)
        assert confirmed["subtotal_cents"] == 20500, (
            f"10*1500 + 5*1100 = 20500, got {confirmed['subtotal_cents']}"
        )
        lines = {l["id"]: l for l in list_order_lines(order["id"])}
        assert lines[line2["id"]]["extended_price_cents"] == 5500
        assert lines[line2["id"]]["unit_price_cents"] == 1100

    def test_confirm_applies_seasonal_adjustment_on_summed_subtotal(self):
        """PRD §3.6: "The seasonal uplift `seasonal_adjustment_cents` applies
        the `SeasonalPriceIndex` band whose half-open window covers
        `order_date` — or a neutral ten thousand basis points when no band
        covers it — computed as the `subtotal_cents` multiplied by the excess
        of `multiplier_bp` over ten thousand, divided by ten thousand, and
        rounded half-up to whole cents."
        PRD §3.6: "The `total_cents` is the subtotal plus the seasonal
        adjustment minus the applied credit"

        Design: Difficulty/combinatorial_formula/order_pricing_per_line_rounding_then_sum
        """
        publish_seasonal_index()  # PEAK-2026-Q3 at 11000 bp
        spec = create_active_spec()
        customer = create_customer("RoundTripper")
        order = create_order(customer["id"], spec["id"], 10, "NEW")
        add_order_line(order["id"], spec["id"], 5, "A")
        confirmed = validate_success(api_client.confirm_order(
            order["id"], {"expected_order_version": order["version"]}, SALES))
        # 20500 * (11000 - 10000) / 10000 = 2050 (computed on the SUMMED
        # subtotal, not per line)
        assert confirmed["seasonal_adjustment_cents"] == 2050, (
            f"expected 2050, got {confirmed['seasonal_adjustment_cents']}"
        )
        assert confirmed["pool_credit_applied_cents"] == 0
        assert confirmed["total_cents"] == 22550, (
            f"20500 + 2050 - 0 = 22550, got {confirmed['total_cents']}"
        )


class TestCancelCompensation:

    def test_confirm_debits_pool_credit_up_to_invoice(self):
        """PRD §3.6: "`pool_credit_applied_cents` is the lesser of the
        customer's `pool_credit_balance_cents` and the sum of `subtotal_cents`
        and `seasonal_adjustment_cents`, and the customer's
        `pool_credit_balance_cents` is debited by that same amount in ledger
        sync."

        Design: Difficulty/compensating_invariant/pool_credit_balance_cancel_compensation
        """
        spec, _lot, _c = setup_sellable_world(lot_quantity=500)
        customer, _ret = setup_customer_with_credit(
            spec["id"], company_name="InvariantCust", delivered_qty=5,
            return_count=4, return_grade="A")
        assert customer["pool_credit_balance_cents"] == 2800
        order = create_order(customer["id"], spec["id"], 3, "NEW")
        confirmed = validate_success(api_client.confirm_order(
            order["id"], {"expected_order_version": order["version"]}, SALES))
        assert confirmed["subtotal_cents"] == 4500
        assert confirmed["pool_credit_applied_cents"] == 2800, (
            "credit application caps at the customer's balance: min(2800, 4500)"
        )
        assert confirmed["total_cents"] == 1700
        mid = get_customer(customer["id"])
        assert mid["pool_credit_balance_cents"] == 0, (
            f"confirm must debit the applied credit, "
            f"got {mid['pool_credit_balance_cents']}"
        )

    def test_cancel_recredits_exactly_the_applied_credit(self):
        """PRD §3.6: "Cancelling re-credits the customer: if
        `pool_credit_applied_cents` is greater than zero, that amount returns
        to the customer's `pool_credit_balance_cents` as compensation, and all
        `OPEN` lines move to `CANCELLED`."
        PRD §3.6: "Cancellation is available from `DRAFT` or `CONFIRMED` (else
        `ERR_ORDER_NOT_CANCELLABLE`)."

        Design: Difficulty/compensating_invariant/pool_credit_balance_cancel_compensation
        """
        spec, _lot, _c = setup_sellable_world(lot_quantity=500)
        customer, _ret = setup_customer_with_credit(
            spec["id"], company_name="InvariantCust", delivered_qty=5,
            return_count=4, return_grade="A")
        balance_before = customer["pool_credit_balance_cents"]
        assert balance_before == 2800
        order = create_order(customer["id"], spec["id"], 3, "NEW")
        confirmed = validate_success(api_client.confirm_order(
            order["id"], {"expected_order_version": order["version"]}, SALES))
        assert confirmed["pool_credit_applied_cents"] == 2800
        cancelled = validate_success(api_client.cancel_order(
            order["id"], SALES))
        assert cancelled["fulfillment_status"] == "CANCELLED"
        after = get_customer(customer["id"])
        assert after["pool_credit_balance_cents"] == balance_before, (
            f"confirm-then-cancel must be drift-free: expected "
            f"{balance_before}, got {after['pool_credit_balance_cents']}"
        )


class TestImmediateConsistency:

    def test_confirm_response_carries_pricing_immediately(self):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify
        a resource will return the created or updated resource object in the
        data field."
        PRD §3.6: "Confirmation computes each `OPEN` line's
        `extended_price_cents` as `quantity` times `unit_price_cents` rounded
        half-up to whole cents — per line first, then summed into
        `subtotal_cents`, never summed and then rounded."

        Design: Corner/consistency_model/immediate_visibility_of_confirm_pricing
        """
        _spec, _lot, customer = setup_sellable_world(
            "ImmCust", lot_quantity=500)
        order = create_order(customer["id"], _spec["id"], 2, "NEW")
        resp = api_client.confirm_order(
            order["id"], {"expected_order_version": order["version"]}, SALES)
        confirmed = validate_success(resp)
        # No seasonal band and no credit: 2 * 1500 = 3000 straight through.
        assert confirmed["subtotal_cents"] == 3000
        assert confirmed["seasonal_adjustment_cents"] == 0
        assert confirmed["total_cents"] == 3000
        reread = get_order(order["id"])
        assert reread["subtotal_cents"] == confirmed["subtotal_cents"]
        assert reread["total_cents"] == confirmed["total_cents"]
        assert reread["version"] == confirmed["version"]
