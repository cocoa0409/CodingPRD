"""Order lifecycle: creation defaults, frozen lines, terminal lockdown,
payments against the financial axis, the parallel-dimension discipline,
cancel cascades, the receivable invariant, RBAC denial, and immediate
read-after-write visibility."""
from test_helpers import (
    ApiErrorId,
    FinancialStatus,
    FulfillmentStatus,
    assert_purchase_order,
    confirm_order,
    create_case,
    create_customer,
    create_order,
    create_order_with_line,
    create_product,
    get_order,
    get_partner,
    set_clock,
    setup_allocated_order,
    setup_confirmed_order,
    setup_customer_with_license,
    validate_error,
    validate_success,
)


class TestOrderCreationDefaults:
    def test_new_order_initializes_statuses_and_zero_invoice(
        self, api, order_manager_headers
    ):
        """PRD §3.4: "A new order's `fulfillment_status` is `DRAFT` and its
        `financial_status` is `UNBILLED` — the two dimensions evolve
        independently of one another — with `invoice_total_cents` and
        `invoice_balance_cents` both zero."

        Design: Corner/entities/computed_fields_ignore_client_input
        """
        customer = create_customer(name="CompRx", credit_limit_cents=5000)
        resp = api.create_purchase_order(
            {"customer_id": customer["id"], "ship_to_state": "CA"},
            order_manager_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert_purchase_order(data)
        assert data["fulfillment_status"] == FulfillmentStatus.DRAFT.value
        assert data["financial_status"] == FinancialStatus.UNBILLED.value
        assert data["invoice_total_cents"] == 0
        assert data["invoice_balance_cents"] == 0


class TestOrderInvalidTransitions:
    def test_cancel_terminal_order_rejected(self, api, order_manager_headers):
        """PRD §3.5: "Cancellation by an `OrderManager` is available while the
        order is `DRAFT` or `CONFIRMED` (`ERR_ORDER_NOT_CANCELLABLE` otherwise)
        and lands in the terminal `CANCELLED` state with a `version` increment."

        Design: Corner/state_machines/cancel_terminal_order_rejected
        """
        customer = create_customer(name="TermRx", credit_limit_cents=5000)
        order = create_order(customer["id"])
        cancel1 = api.cancel_order(order["id"], order_manager_headers)
        assert validate_success(cancel1)["fulfillment_status"] == FulfillmentStatus.CANCELLED.value

        resp = api.cancel_order(order["id"], order_manager_headers)
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_CANCELLABLE)
        # No side effect fired twice: the order is still simply CANCELLED.
        assert get_order(order["id"])["fulfillment_status"] == FulfillmentStatus.CANCELLED.value

    def test_deliver_from_draft_rejected(self, api, warehouse_operator_headers):
        """PRD §3.5: "Delivery by a `WarehouseOperator` moves a `SHIPPED` order
        to `DELIVERED` (`ERR_ORDER_NOT_SHIPPED` otherwise) and increments
        `version`".

        Design: Corner/state_machines/deliver_from_draft_rejected
        """
        customer = create_customer(name="DelRx", credit_limit_cents=5000)
        order = create_order(customer["id"])
        resp = api.deliver_order(order["id"], warehouse_operator_headers)
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_SHIPPED)
        assert get_order(order["id"])["fulfillment_status"] == FulfillmentStatus.DRAFT.value

    def test_add_line_to_confirmed_order_rejected(self, api, order_manager_headers):
        """PRD §3.4: "Lines are added to a `DRAFT` order one at a time...
        Adding a line to an order that has left `DRAFT` is rejected with
        `ERR_ORDER_NOT_DRAFT`."

        Design: Corner/state_machines/add_line_to_confirmed_order_rejected
        """
        set_clock()
        customer, _lic = setup_customer_with_license(name="FrzRx")
        product = create_product(wholesale_acquisition_cost_cents=100)
        order = setup_confirmed_order(customer["id"], product["id"], 1)

        resp = api.add_order_line(
            order["id"], {"product_id": product["id"], "quantity_requested": 1},
            order_manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_DRAFT)


class TestPayments:
    def _setup_invoiced_order(self, name, quantity=4, wac=1000):
        """CONFIRMED order (financial INVOICED) for 4 x 1000 = 4000."""
        set_clock()
        customer, _lic = setup_customer_with_license(name=name)
        product = create_product(wholesale_acquisition_cost_cents=wac)
        order = setup_confirmed_order(customer["id"], product["id"], quantity)
        return customer, product, order

    def test_payment_exact_payoff_transitions_to_paid(self, api, billing_clerk_headers):
        """PRD §3.7: "a payment exactly equal to the balance settles it — the
        balance becomes zero and the status becomes the terminal `PAID`. Either
        way, the posted amount reduces both the order's `invoice_balance_cents`
        and the customer's `open_receivable_cents` by the same figure."

        Design: Corner/calculations/payment_exact_payoff_transitions_to_paid
        """
        customer, _p, order = self._setup_invoiced_order("PayRx")
        assert order["invoice_total_cents"] == 4000

        resp = api.post_payment(order["id"], {"amount_cents": 4000}, billing_clerk_headers)
        data = validate_success(resp, expected_status=201)
        assert data["financial_status"] == FinancialStatus.PAID.value
        assert data["invoice_balance_cents"] == 0
        assert get_partner(customer["id"])["open_receivable_cents"] == 0

    def test_payment_over_balance_rejected(self, api, billing_clerk_headers):
        """PRD §3.7: "The `amount_cents` must be strictly positive and no greater
        than the outstanding `invoice_balance_cents`, failing which the posting
        is rejected with `ERR_PAYMENT_AMOUNT_INVALID` (HTTP 422)."

        Design: Corner/calculations/payment_over_balance_rejected
        """
        _customer, _p, order = self._setup_invoiced_order("OvpRx")

        resp = api.post_payment(order["id"], {"amount_cents": 4001}, billing_clerk_headers)
        validate_error(resp, ApiErrorId.ERR_PAYMENT_AMOUNT_INVALID)
        assert get_order(order["id"])["invoice_balance_cents"] == 4000
        assert get_order(order["id"])["financial_status"] == FinancialStatus.INVOICED.value


class TestParallelDimensions:
    """Fulfillment and financial status evolve independently on the same order."""

    def _setup_allocated_order_with_case(self):
        set_clock()
        customer, _lic = setup_customer_with_license(name="ParRx")
        product = create_product(wholesale_acquisition_cost_cents=1000)
        order = setup_allocated_order(customer["id"], product["id"], 4)
        case = create_case(product["id"])
        return customer, product, order, case

    def test_payment_moves_only_financial_axis(self, api, billing_clerk_headers):
        """PRD §3.4: "the two dimensions evolve independently of one another".
        PRD §3.7: "A payment smaller than the balance moves the order to
        `PARTIALLY_PAID`... the posted amount reduces both the order's
        `invoice_balance_cents` and the customer's `open_receivable_cents` by
        the same figure."

        A 1000-cent payment against a 4000-cent invoice flips the financial
        dimension to PARTIALLY_PAID and leaves fulfillment ALLOCATED.

        Design: Difficulty/non_linear_state_machine/purchase_order_parallel_dimensions
        """
        customer, _p, order, _case = self._setup_allocated_order_with_case()
        assert order["fulfillment_status"] == FulfillmentStatus.ALLOCATED.value
        assert order["invoice_balance_cents"] == 4000

        resp = api.post_payment(order["id"], {"amount_cents": 1000}, billing_clerk_headers)
        data = validate_success(resp, expected_status=201)
        assert data["financial_status"] == FinancialStatus.PARTIALLY_PAID.value
        assert data["invoice_balance_cents"] == 3000
        assert data["fulfillment_status"] == FulfillmentStatus.ALLOCATED.value, (
            "payment must not move the fulfillment dimension"
        )
        assert get_partner(customer["id"])["open_receivable_cents"] == 3000

    def test_ship_succeeds_on_partially_paid_order(
        self, api, billing_clerk_headers, warehouse_operator_headers
    ):
        """PRD §3.4: "the two dimensions evolve independently of one another".
        PRD §3.5: "the order must be `CONFIRMED` or `ALLOCATED`
        (`ERR_ORDER_NOT_SHIPPABLE`)" — the ship gate reads the fulfillment
        dimension only, so a PARTIALLY_PAID order ships normally.

        Design: Difficulty/non_linear_state_machine/purchase_order_parallel_dimensions
        """
        _customer, _p, order, case = self._setup_allocated_order_with_case()
        pay = api.post_payment(order["id"], {"amount_cents": 1000}, billing_clerk_headers)
        validate_success(pay, expected_status=201)

        resp = api.ship_order(
            order["id"], {"segregation_mode": "STANDARD", "case_ids": [case["id"]]},
            warehouse_operator_headers,
        )
        data = validate_success(resp)
        assert data["fulfillment_status"] == FulfillmentStatus.SHIPPED.value
        assert data["financial_status"] == FinancialStatus.PARTIALLY_PAID.value
        assert data["invoice_balance_cents"] == 3000


class TestCancelCascade:
    def _setup_confirmed_10000(self):
        set_clock()
        customer, _lic = setup_customer_with_license(name="CasRx")
        product = create_product(wholesale_acquisition_cost_cents=2000)
        order = setup_confirmed_order(customer["id"], product["id"], 5)
        return customer, product, order

    def test_cancel_confirmed_order_flips_financial_to_credited(
        self, api, order_manager_headers
    ):
        """PRD §3.5: "Cancelling a `CONFIRMED` order unwinds it: if the
        financial dimension is `INVOICED`, it flips to `CREDITED`, the
        customer's `open_receivable_cents` falls by the outstanding
        `invoice_balance_cents`, and the balance is zeroed".

        Design: Difficulty/transitive_cascade/order_cancel_cascade_depth2
        """
        _customer, _p, order = self._setup_confirmed_10000()
        assert order["invoice_total_cents"] == 10000

        resp = api.cancel_order(order["id"], order_manager_headers)
        data = validate_success(resp)
        assert data["fulfillment_status"] == FulfillmentStatus.CANCELLED.value
        assert data["financial_status"] == FinancialStatus.CREDITED.value
        assert data["invoice_balance_cents"] == 0

    def test_cancel_confirmed_order_zeroes_customer_receivable(
        self, api, order_manager_headers
    ):
        """PRD §3.5: "the customer's `open_receivable_cents` falls by the
        outstanding `invoice_balance_cents`, and the balance is zeroed".
        PRD §3.7: "a partner's `open_receivable_cents` always equals the
        outstanding invoice balances of that partner's orders in `INVOICED` or
        `PARTIALLY_PAID`".

        Hop 2 of the cascade: the partner ledger mutation is caused by the
        order's financial flip, not by the cancel directly.

        Design: Difficulty/transitive_cascade/order_cancel_cascade_depth2
        """
        customer, _p, order = self._setup_confirmed_10000()
        assert get_partner(customer["id"])["open_receivable_cents"] == 10000

        validate_success(api.cancel_order(order["id"], order_manager_headers))
        assert get_partner(customer["id"])["open_receivable_cents"] == 0


class TestReceivableInvariant:
    """open_receivable_cents is conserved across confirm/cancel pairs."""

    def _setup(self):
        set_clock()
        customer, _lic = setup_customer_with_license(name="InvRx")
        product = create_product(wholesale_acquisition_cost_cents=2000)
        order, _line = create_order_with_line(customer["id"], product["id"], 5)
        return customer, product, order

    def test_confirm_raises_receivable_by_invoice_total(self, api, order_manager_headers):
        """PRD §3.4: "The same step moves the order `DRAFT` → `CONFIRMED` and
        `UNBILLED` → `INVOICED`, raises the customer's `open_receivable_cents`
        by the invoice total, and increments the order's `version`."
        PRD §3.7: "a partner's `open_receivable_cents` always equals the
        outstanding invoice balances of that partner's orders in `INVOICED` or
        `PARTIALLY_PAID`".

        Design: Difficulty/compensating_invariant/receivable_confirm_cancel_invariant
        """
        customer, _p, order = self._setup()
        assert get_partner(customer["id"])["open_receivable_cents"] == 0

        resp = api.confirm_order(order["id"], order_manager_headers)
        data = validate_success(resp)
        assert data["invoice_total_cents"] == 10000
        assert data["invoice_balance_cents"] == 10000
        assert data["financial_status"] == FinancialStatus.INVOICED.value
        assert get_partner(customer["id"])["open_receivable_cents"] == 10000

    def test_cancel_restores_receivable_to_pre_confirm_value(
        self, api, order_manager_headers
    ):
        """PRD §3.5: "if the financial dimension is `INVOICED`, it flips to
        `CREDITED`, the customer's `open_receivable_cents` falls by the
        outstanding `invoice_balance_cents`, and the balance is zeroed".
        PRD §3.7: "every event that creates, reduces, or extinguishes a balance
        — order confirmation, payment posting, cancellation-with-credit, return
        credit — rebalances it immediately."

        The confirm/cancel pair compensates exactly: the receivable returns to
        its pre-confirm value of zero.

        Design: Difficulty/compensating_invariant/receivable_confirm_cancel_invariant
        """
        customer, _p, order = self._setup()
        confirm_order(order["id"])
        assert get_partner(customer["id"])["open_receivable_cents"] == 10000

        validate_success(api.cancel_order(order["id"], order_manager_headers))
        cancelled = get_order(order["id"])
        assert cancelled["invoice_balance_cents"] == 0
        assert get_partner(customer["id"])["open_receivable_cents"] == 0


class TestRbacDenials:
    def test_warehouse_operator_cannot_confirm_order(
        self, api, warehouse_operator_headers
    ):
        """PRD §2.1: "A request whose declared role is not permitted to invoke
        the target endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403);
        the permission matrix itself is given by the Authorized Role(s) column
        of §4."
        PRD §4: POST /wholesale/purchase-orders/{orderId}/confirm —
        OrderManager only.

        Design: Corner/rbac/warehouse_operator_cannot_confirm_order
        """
        customer = create_customer(name="RbRx", credit_limit_cents=5000)
        order = create_order(customer["id"])
        resp = api.confirm_order(order["id"], warehouse_operator_headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


class TestImmediateVisibility:
    def test_confirm_response_and_follow_up_read_agree(self, api, order_manager_headers):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field."
        PRD §3.4: "the provisional `invoice_total_cents` is the sum of those
        extended prices; `invoice_balance_cents` starts equal to the total. The
        same step moves the order `DRAFT` → `CONFIRMED` and `UNBILLED` →
        `INVOICED`".

        Design: Corner/consistency_model/immediate_visibility_after_mutation
        """
        set_clock()
        customer, _lic = setup_customer_with_license(name="ImRx")
        product = create_product(wholesale_acquisition_cost_cents=1500)
        order, _line = create_order_with_line(customer["id"], product["id"], 2)

        resp = api.confirm_order(order["id"], order_manager_headers)
        data = validate_success(resp)
        assert data["fulfillment_status"] == FulfillmentStatus.CONFIRMED.value
        assert data["financial_status"] == FinancialStatus.INVOICED.value
        assert data["invoice_total_cents"] == 3000  # provisional: 2 x 1500

        follow_up = api.get_purchase_order(order["id"], order_manager_headers)
        fetched = validate_success(follow_up)
        assert fetched["fulfillment_status"] == FulfillmentStatus.CONFIRMED.value
        assert fetched["invoice_total_cents"] == 3000
        assert fetched["financial_status"] == FinancialStatus.INVOICED.value
