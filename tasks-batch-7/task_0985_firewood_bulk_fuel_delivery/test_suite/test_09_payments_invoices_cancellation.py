"""Payments, invoices, refunds, and order cancellation (PRD §2.8, §3.5, §3.8)."""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data, validate_paginated,
    create_order_payload, order_line, create_payment_payload,
    set_clock, create_customer, create_product, create_route, create_window,
    create_order, setup_catalog_with_route, submit_and_pay, pay_order_in_full,
    create_delivered_order, assert_stock_conservation,
    TEST_USERS, make_customer_headers,
)

CS = TEST_USERS["customer_service_headers"]
OM = TEST_USERS["operations_manager_headers"]
RP = TEST_USERS["route_planner_headers"]


class TestAccountStandingGate:
    def _setup_suspended_customer_with_draft(self, api):
        set_clock("2026-08-01T00:00:00Z")
        customer, product, _route = setup_catalog_with_route(
            postal_code="20014", prefixes=("2",), sku="P14", available_qty=10)
        order = create_order(customer["id"], product["id"], 1.0,
                             postal_code="20014",
                             requested_delivery_date="2026-08-15")
        get_success_data(api.suspend_customer(
            customer["id"], {"reason": "manual review"}, OM))
        return customer, product, order

    def test_order_submit_gated_by_customer_account_status(self, api):
        """PRD §3.5: "the customer's account must be `ACTIVE` (a suspended
        account's submission is rejected with `ERR_ACCOUNT_INACTIVE`), and — if
        a subscription is attached — the subscription must be `ACTIVE` with the
        requested delivery date inside its season window."

        Design: Difficulty/cross_entity_state_dependency/order_submit_gated_by_customer_account_status
        """
        _customer, _product, order = self._setup_suspended_customer_with_draft(api)
        res = api.submit_order(order["id"], CS)
        validate_error(res, "ERR_ACCOUNT_INACTIVE", expected_status=409)

    def test_order_create_gated_by_customer_account_status(self, api):
        """PRD §2.8: "Account standing: the customer's `account_status` is
        `ACTIVE` for any state-mutating endpoint invoked by or on behalf of that
        customer — otherwise `ERR_ACCOUNT_INACTIVE` (HTTP 409). Applies to
        `POST /api/v1/orders`, `POST /api/v1/subscriptions`, and
        `POST /api/v1/orders/{id}/submit`."

        Design: Difficulty/cross_entity_state_dependency/order_submit_gated_by_customer_account_status
        """
        set_clock("2026-08-01T00:00:00Z")
        customer, product, _route = setup_catalog_with_route(
            postal_code="20014", prefixes=("2",), sku="P14", available_qty=10)
        get_success_data(api.suspend_customer(
            customer["id"], {"reason": "manual review"}, OM))
        res = api.create_order(create_order_payload(
            customer["id"], [order_line(product["id"], 1.0)],
            delivery_postal_code="20014",
            requested_delivery_date="2026-08-15"), CS)
        validate_error(res, "ERR_ACCOUNT_INACTIVE", expected_status=409)


class TestStockAvailability:
    def test_insufficient_stock_at_submit(self, api):
        """PRD §3.5: "Stock is reserved at this moment: each line's product
        must have `available_qty` of at least the line's `quantity`, or the
        submit fails with `ERR_INSUFFICIENT_STOCK`; on success each product's
        `available_qty` decreases and its `reserved_qty` increases by the
        reserved amount, with the product's `version` incrementing per line."

        Design: Corner/validations/insufficient_stock_at_submit
        """
        set_clock("2026-08-01T00:00:00Z")
        customer, product, _route = setup_catalog_with_route(
            sku="PST", available_qty=1.0)
        order = create_order(customer["id"], product["id"], 2.0)
        res = api.submit_order(order["id"], CS)
        validate_error(res, "ERR_INSUFFICIENT_STOCK", expected_status=422)


class TestStockConservation:
    def _setup(self, api):
        set_clock("2026-08-01T00:00:00Z")
        customer, product, _route = setup_catalog_with_route(
            postal_code="60018", prefixes=("6",), sku="P18", available_qty=5.0)
        order = create_order(customer["id"], product["id"], 2.5,
                             postal_code="60018",
                             requested_delivery_date="2026-08-15")
        return customer, product, order

    def test_stock_conservation_reserve_on_submit(self, api):
        """PRD §3.5: "on success each product's `available_qty` decreases and
        its `reserved_qty` increases by the reserved amount, with the product's
        `version` incrementing per line. The order's pricing is recomputed in
        full, an invoice is issued per §3.8, and the order moves from `DRAFT`
        to `PENDING_PAYMENT`."
        Submitting a 2.5-unit line against 5.0 available leaves 2.5 available
        and 2.5 reserved; the total stock is conserved.

        Design: Difficulty/compensating_invariant/stock_conservation_reserve_then_cancel_releases
        """
        _customer, product, order = self._setup(api)
        validate_success(api.submit_order(order["id"], CS), 200)
        product_after = get_success_data(api.get_product(product["id"], OM))
        assert product_after["available_qty"] == pytest.approx(2.5)
        assert product_after["reserved_qty"] == pytest.approx(2.5)
        assert_stock_conservation(product_after, 5.0)

    def test_stock_conservation_release_on_cancel(self, api):
        """PRD §3.8: "From `PENDING_PAYMENT`, the same actor — the owner or an
        `OperationsManager` — cancels, releasing every line's reservation (each
        product's `available_qty` is restored and `reserved_qty` reduced, with
        the product's `version` incrementing) and, if payment had already
        settled, issuing a `REFUND` event that drives the invoice toward
        `REFUNDED`."
        After reserve-then-cancel, available returns to 5.0 and reserved to 0.

        Design: Difficulty/compensating_invariant/stock_conservation_reserve_then_cancel_releases
        """
        _customer, product, order = self._setup(api)
        validate_success(api.submit_order(order["id"], CS), 200)
        validate_success(api.cancel_order(
            order["id"], {"reason": "changed mind"}, CS), 200)
        product_after = get_success_data(api.get_product(product["id"], OM))
        assert product_after["available_qty"] == pytest.approx(5.0)
        assert product_after["reserved_qty"] == pytest.approx(0.0)
        assert_stock_conservation(product_after, 5.0)


class TestInvoiceSnapshot:
    def test_invoice_amount_snapshot_immutable_after_issuance(self, api):
        """PRD §3.8: "An invoice is born at submission: the moment an order
        enters `PENDING_PAYMENT`, the system issues one whose `amount_cents`
        snapshots the order's `total_cents` at issuance and never changes
        thereafter, whose `due_date` is seven days after the order's
        `requested_delivery_date`, whose `invoice_number` is server-minted in
        the form `INV-<season_year>-<6-digit-seq>`, and whose `issued_at` is
        stamped."
        requested_delivery_date 2026-08-15 -> due_date 2026-08-22.

        Design: Corner/calculations/invoice_amount_snapshot_immutable_after_issuance
        """
        set_clock("2026-08-01T00:00:00Z")
        customer, product, _route = setup_catalog_with_route(sku="PIA")
        order = create_order(customer["id"], product["id"], 1.0,
                             requested_delivery_date="2026-08-15")
        validate_success(api.submit_order(order["id"], CS), 200)
        order_after = get_success_data(api.get_order(order["id"], CS))
        invoices = get_success_data(api.list_invoices(
            CS, params={"order_id": order["id"]}))
        assert len(invoices) == 1
        invoice = invoices[0]
        assert invoice["amount_cents"] == order_after["total_cents"]
        assert invoice["status"] == "OPEN"
        assert invoice["due_date"] == "2026-08-22"


class TestInvoiceVoid:
    def test_invoice_void_rejected_when_paid_or_order_not_cancelled(self, api):
        """PRD §3.8: "An invoice that should never have been collected can be
        voided by an `OperationsManager`, moving it from `OPEN` to the terminal
        `VOID` state, but only while it is `OPEN` with `paid_cents` of 0 and
        its order already `CANCELLED`; otherwise the void is rejected with
        `ERR_INVOICE_NOT_VOIDABLE`."

        Design: Corner/validations/invoice_void_rejected_when_paid_or_order_not_cancelled
        """
        set_clock("2026-08-01T00:00:00Z")
        customer, product, _route = setup_catalog_with_route(sku="PIV")
        order = create_order(customer["id"], product["id"], 1.0)
        validate_success(api.submit_order(order["id"], CS), 200)
        invoices = get_success_data(api.list_invoices(
            CS, params={"order_id": order["id"]}))
        res = api.void_invoice(invoices[0]["id"], OM)
        validate_error(res, "ERR_INVOICE_NOT_VOIDABLE", expected_status=409)

    def test_route_planner_cannot_void_invoice(self, api):
        """PRD §2.1: "A request whose role is not permitted on the target
        endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §4: POST /api/v1/invoices/{id}/void — Authorized Role(s):
        OperationsManager.

        Design: Corner/rbac/route_planner_cannot_void_invoice
        """
        set_clock("2026-08-01T00:00:00Z")
        customer, product, _route = setup_catalog_with_route(sku="PRP")
        order = create_order(customer["id"], product["id"], 1.0)
        validate_success(api.submit_order(order["id"], CS), 200)
        validate_success(api.cancel_order(
            order["id"], {"reason": "cust"},
            make_customer_headers(customer["id"])), 200)
        invoices = get_success_data(api.list_invoices(
            CS, params={"order_id": order["id"]}))
        res = api.void_invoice(invoices[0]["id"], RP)
        validate_error(res, "ERR_UNAUTHORIZED", expected_status=403)


class TestRefundConservation:
    def _setup_paid_order(self, api):
        set_clock("2026-08-01T00:00:00Z")
        customer, product, route = setup_catalog_with_route(
            postal_code="10019", prefixes=("10019",), sku="P19",
            available_qty=10, capacity=50.0)
        order = create_order(customer["id"], product["id"], 1.0,
                             postal_code="10019",
                             requested_delivery_date="2026-08-15")
        validate_success(api.submit_order(order["id"], CS), 200)
        order = pay_order_in_full(order["id"])
        invoices = get_success_data(api.list_invoices(
            CS, params={"order_id": order["id"]}))
        return customer, product, order, invoices[0]

    def test_invoice_payment_conservation_capture_then_refund_zeros_out(self, api):
        """PRD §3.8: "Refunding the full unrefunded balance from `PAID`, or the
        remaining balance from `PARTIALLY_REFUNDED` so cumulative refunds equal
        cumulative payments, moves the order to `REFUNDED` and the invoice to
        `REFUNDED` with `settled_at` overwritten to the refund timestamp."

        Design: Difficulty/compensating_invariant/invoice_payment_conservation_capture_then_refund_zeros_out
        """
        customer, _p, order, invoice = self._setup_paid_order(api)
        total = order["total_cents"]
        invoice_paid = get_success_data(api.get_invoice(invoice["id"], CS))
        assert invoice_paid["paid_cents"] == total
        assert invoice_paid["status"] == "PAID"
        validate_success(api.post_payment(order["id"], create_payment_payload(
            "REFUND", total), CS), 201)
        invoice_after = get_success_data(api.get_invoice(invoice["id"], CS))
        assert invoice_after["paid_cents"] == total
        assert invoice_after["refunded_cents"] == total
        assert invoice_after["paid_cents"] - invoice_after["refunded_cents"] == 0
        assert invoice_after["status"] == "REFUNDED"
        order_after = get_success_data(api.get_order(order["id"], CS))
        assert order_after["payment_status"] == "REFUNDED"

    def test_full_refund_credits_customer_wallet(self, api):
        """PRD §3.8: "A partial refund — strictly less than the unrefunded paid
        balance — moves a `PAID` order to `PARTIALLY_REFUNDED`, accrues
        `refunded_cents`, and credits the customer's wallet under the clamping
        rule." The full refund lands in the wallet: money that left the invoice
        is conserved as customer credit.

        Design: Difficulty/compensating_invariant/invoice_payment_conservation_capture_then_refund_zeros_out
        """
        customer, _p, order, invoice = self._setup_paid_order(api)
        total = order["total_cents"]
        validate_success(api.post_payment(order["id"], create_payment_payload(
            "REFUND", total), CS), 201)
        customer_after = get_success_data(api.get_customer(customer["id"], CS))
        assert customer_after["credit_balance_cents"] == total


class TestCustomerClose:
    def test_customer_close_with_outstanding_refund_rejected(self, api):
        """PRD §2.8: "Outstanding refund: a customer account closes only when
        no refund remains owed — otherwise `ERR_OUTSTANDING_REFUND` (HTTP 409)."
        PRD §3.1: "any debit that would push it below zero is clamped to 0 with
        the excess carried into `outstanding_refund_cents` as a negative-owed
        balance — a debit standing against future refunds."
        A -500 wallet adjustment on a zero-balance wallet carries 500 into
        outstanding_refund_cents, blocking the close.

        Design: Corner/validations/customer_close_with_outstanding_refund_rejected
        """
        set_clock("2026-08-01T00:00:00Z")
        customer = create_customer()
        get_success_data(api.adjust_wallet(
            customer["id"], {"amount_cents": -500, "reason": "seed outstanding"}, OM))
        res = api.close_customer(customer["id"], OM)
        validate_error(res, "ERR_OUTSTANDING_REFUND", expected_status=409)


class TestAuthentication:
    def test_err_unauthenticated_on_missing_headers(self, api):
        """PRD §2.1: "A request with missing headers, or with a role outside
        this declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/errors/err_unauthenticated_on_missing_headers
        """
        set_clock()
        res = api.get_customer(
            "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", headers={})
        validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)


class TestPagination:
    def test_list_orders_pagination_default(self, api):
        """PRD §2.3: "`limit` sets the maximum number of items returned; it
        defaults to 10, with a minimum of 1 and a maximum of 100."
        PRD §2.2: "The `meta` object of a list response carries the pagination
        fields `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/endpoints/list_orders_pagination_default
        """
        set_clock("2026-08-01T00:00:00Z")
        customer, product, _route = setup_catalog_with_route(
            sku="PPG", available_qty=100)
        for _i in range(12):
            create_order(customer["id"], product["id"], 1.0)
        res = api.list_orders(CS, params={"customer_id": customer["id"]})
        data, meta = validate_paginated(res)
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert meta["total_count"] == 12
        assert meta["has_more"] is True
        assert len(data) == 10


class TestImmediateConsistency:
    def test_immediate_consistency_on_order_submit(self, api):
        """PRD §3.5: "on success each product's `available_qty` decreases and
        its `reserved_qty` increases by the reserved amount, with the product's
        `version` incrementing per line. The order's pricing is recomputed in
        full, an invoice is issued per §3.8, and the order moves from `DRAFT`
        to `PENDING_PAYMENT`."
        The submit response and an immediate follow-up read reflect the new
        state atomically, with no consistency lag.

        Design: Corner/consistency_model/immediate_consistency_on_order_submit
        """
        set_clock("2026-08-01T00:00:00Z")
        customer, product, _route = setup_catalog_with_route(
            sku="PIC", available_qty=10)
        order = create_order(customer["id"], product["id"], 1.0)
        submitted = validate_success(api.submit_order(order["id"], CS), 200)
        assert submitted["fulfillment_status"] == "PENDING_PAYMENT"
        fetched = validate_success(api.get_order(order["id"], CS), 200)
        assert fetched["fulfillment_status"] == "PENDING_PAYMENT"
        product_after = get_success_data(api.get_product(product["id"], OM))
        assert product_after["available_qty"] == pytest.approx(9.0)
        assert product_after["reserved_qty"] == pytest.approx(1.0)
