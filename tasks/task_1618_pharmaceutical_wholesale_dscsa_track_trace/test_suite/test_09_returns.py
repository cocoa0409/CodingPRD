"""Returns and credit issuance: lodgement limits, the 48-hour cold-chain
window, restock-rate tiers, the pinned rounding order, and credit side
effects on the order and the receivable ledger."""
from test_helpers import (
    ApiErrorId,
    FulfillmentStatus,
    ReturnStatus,
    allocate_order,
    create_product,
    get_order,
    get_partner,
    get_single_line,
    lodge_return,
    set_clock,
    setup_allocated_order,
    setup_customer_with_license,
    setup_delivered_order,
    setup_return_received,
    setup_shortage_order,
    setup_shortage_product,
    validate_error,
    validate_success,
)


class TestReturnCreditRounding:
    """Nested rounding: the single floor applies to the whole product of
    quantity x unit price x rate. Each scenario is a cold-chain order for
    3 x 9999 delivered at the default clock, with the return received one day
    later (inside both the 48-hour lodging window and the two-day cold
    restock window)."""

    def _receive_cold_return(self, api, warehouse_operator_headers):
        set_clock()
        customer, product, order, _case, ret = setup_return_received(
            cold_chain=True, quantity=3, wac_cents=9999
        )
        set_clock("2026-08-02T00:00:00Z")  # 1 day after delivery
        received = validate_success(api.receive_return(ret["id"], warehouse_operator_headers))
        assert received["return_status"] == ReturnStatus.RECEIVED.value
        return customer, product, order, ret

    def test_cold_chain_credit_uses_single_floor_on_total(
        self, api, warehouse_operator_headers, billing_clerk_headers
    ):
        """PRD §3.8: "The `credit_amount_cents` is the returned quantity times
        the order line's `unit_price_cents` for that product times the
        applicable restock rate, rounded down to a whole cent."
        PRD §3.8: "Cold-chain product earns half credit when no more than two
        days have elapsed and nothing afterward."

        One day after delivery the half rate applies, and the single floor
        lands on the total: floor(3 x 9999 x 0.50) = floor(14998.5) = 14998 —
        a per-unit-first rounding would yield 14997 and is not the pinned
        order.

        Design: Difficulty/combinatorial_formula/return_credit_nested_rounding_order
        """
        _customer, _product, _order, ret = self._receive_cold_return(
            api, warehouse_operator_headers
        )
        resp = api.credit_return(ret["id"], billing_clerk_headers)
        data = validate_success(resp)
        assert data["return_status"] == ReturnStatus.CREDITED.value
        assert data["credit_amount_cents"] == 14998, (
            f"floor(3 * 9999 * 0.50) == 14998, got {data['credit_amount_cents']}"
        )
        assert data["credit_amount_cents"] != 14997

    def test_cold_chain_credit_reduces_order_balance_and_receivable(
        self, api, warehouse_operator_headers, billing_clerk_headers
    ):
        """PRD §3.8: "The credit reduces the order's `invoice_balance_cents`,
        never below zero, and reduces the customer's `open_receivable_cents`
        by the credit amount, likewise clamped at zero".

        The invoice total is 3 x 9999 = 29997; the 14998 credit leaves a
        balance of 14999 and drops the customer's receivable by the same 14998.

        Design: Difficulty/combinatorial_formula/return_credit_nested_rounding_order
        """
        customer, _product, order, ret = self._receive_cold_return(
            api, warehouse_operator_headers
        )
        assert get_order(order["id"])["invoice_balance_cents"] == 29997
        assert get_partner(customer["id"])["open_receivable_cents"] == 29997

        data = validate_success(api.credit_return(ret["id"], billing_clerk_headers))
        assert data["credit_amount_cents"] == 14998

        order_after = get_order(order["id"])
        assert order_after["invoice_balance_cents"] == 29997 - 14998
        partner_after = get_partner(customer["id"])
        assert partner_after["open_receivable_cents"] == 29997 - 14998


class TestReturnCreditTiers:
    def test_return_credit_partial_window_31_to_90_days(
        self, api, warehouse_operator_headers, billing_clerk_headers
    ):
        """PRD §3.8: "The rate turns on the days since delivery, measured in
        whole days with partial days discarded, between the delivery timestamp
        and the current logical clock."
        PRD §3.8: "Any other product earns full credit within thirty days of
        delivery, four-fifths credit from the thirty-first through the
        ninetieth day, and nothing afterward."

        Forty-five days after delivery the four-fifths rate applies:
        floor(5 x 2000 x 0.80) = 8000.

        Design: Corner/calculations/return_credit_partial_window_31_to_90_days
        """
        set_clock()
        _customer, _product, _order, _case, ret = setup_return_received(
            cold_chain=False, quantity=5, wac_cents=2000
        )
        set_clock("2026-09-15T00:00:00Z")  # 45 whole days after delivery
        received = validate_success(api.receive_return(ret["id"], warehouse_operator_headers))
        assert received["return_status"] == ReturnStatus.RECEIVED.value

        data = validate_success(api.credit_return(ret["id"], billing_clerk_headers))
        assert data["credit_amount_cents"] == 8000, (
            f"floor(5 * 2000 * 0.80) == 8000, got {data['credit_amount_cents']}"
        )
        assert data["return_status"] == ReturnStatus.CREDITED.value


class TestColdReturnWindow:
    """Elapsed-duration window: cold-chain returns are receivable while the
    clock is within 48 hours of the order's delivery."""

    def _setup_two_cold_returns(self):
        """One delivered cold-chain order (2 x 1000) with two lodged returns
        of 1 unit each."""
        set_clock()
        product = create_product(is_cold_chain=True, wholesale_acquisition_cost_cents=1000)
        customer, _lic = setup_customer_with_license(name="ColdWin")
        order, _case = setup_delivered_order(
            customer["id"], product["id"], 2, segregation_mode="COLD_CHAIN"
        )
        ret_early = lodge_return(order["id"], product["id"], 1)
        ret_late = lodge_return(order["id"], product["id"], 1)
        return ret_early, ret_late

    def test_cold_return_received_at_exactly_48h(self, api, warehouse_operator_headers):
        """PRD §3.8: "for cold-chain product the return must be lodged within
        48 hours of the order's delivery as measured by the logical clock,
        failing which receipt is rejected with `ERR_COLD_RETURN_WINDOW_EXPIRED`
        (HTTP 422)."

        Delivered at 2026-08-01T00:00:00Z; receipt at 2026-08-03T00:00:00Z is
        exactly 48 hours later — within the window.

        Design: Difficulty/resource_temporal_overlap/cold_chain_return_window_48h
        """
        ret_early, _ret_late = self._setup_two_cold_returns()
        set_clock("2026-08-03T00:00:00Z")
        resp = api.receive_return(ret_early["id"], warehouse_operator_headers)
        data = validate_success(resp)
        assert data["return_status"] == ReturnStatus.RECEIVED.value

    def test_cold_return_rejected_at_48h_plus_one_second(
        self, api, warehouse_operator_headers
    ):
        """PRD §3.8: "for cold-chain product the return must be lodged within
        48 hours of the order's delivery as measured by the logical clock,
        failing which receipt is rejected with `ERR_COLD_RETURN_WINDOW_EXPIRED`
        (HTTP 422)."

        One second past the 48-hour mark the window has closed.

        Design: Difficulty/resource_temporal_overlap/cold_chain_return_window_48h
        """
        _ret_early, ret_late = self._setup_two_cold_returns()
        set_clock("2026-08-03T00:00:01Z")
        resp = api.receive_return(ret_late["id"], warehouse_operator_headers)
        validate_error(resp, ApiErrorId.ERR_COLD_RETURN_WINDOW_EXPIRED)


class TestReturnGates:
    def test_return_qty_exceeds_allocated_rejected(self, api, order_manager_headers):
        """PRD §3.8: "Even at lodgement, the returned quantity may not exceed
        the `quantity_allocated` of the order's line for that product, or the
        request is rejected with `ERR_RETURN_QTY_EXCEEDS_ALLOCATED` (HTTP 422)."

        A shortage allocation grants 6 of 10 requested; lodging a return for 7
        exceeds the granted quantity.

        Design: Corner/validations/return_qty_exceeds_allocated_rejected
        """
        set_clock()
        product, _policy = setup_shortage_product(
            wac_cents=100, pool_units=6, policy_mode="PRO_RATA", min_guarantee_units=0
        )
        _customer, order = setup_shortage_order(product["id"], 10, customer_name="QtyRx")
        allocate_order(order["id"], expected_version=order["version"])
        line = get_single_line(order["id"])
        assert line["quantity_allocated"] == 6

        resp = api.create_return_authorization(
            {
                "order_id": order["id"],
                "product_id": product["id"],
                "quantity_returned": 7,
            },
            order_manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_RETURN_QTY_EXCEEDS_ALLOCATED)

    def test_return_on_unshipped_order_rejected(self, api, warehouse_operator_headers):
        """PRD §3.8: "Physical receipt is a `WarehouseOperator` action with
        four gates: the return must be `REQUESTED` (`ERR_RETURN_NOT_REQUESTED`);
        the referenced order must be `SHIPPED` or `DELIVERED`
        (`ERR_ORDER_NOT_RETURNABLE`)".

        The order was confirmed and fully allocated but never shipped.

        Design: Corner/validations/return_on_unshipped_order_rejected
        """
        set_clock()
        customer, _lic = setup_customer_with_license(name="UnshRx")
        product = create_product(wholesale_acquisition_cost_cents=100)
        order = setup_allocated_order(customer["id"], product["id"], 2)
        assert order["fulfillment_status"] == FulfillmentStatus.ALLOCATED.value
        ret = lodge_return(order["id"], product["id"], 1)
        assert ret["return_status"] == ReturnStatus.REQUESTED.value

        resp = api.receive_return(ret["id"], warehouse_operator_headers)
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_RETURNABLE)
