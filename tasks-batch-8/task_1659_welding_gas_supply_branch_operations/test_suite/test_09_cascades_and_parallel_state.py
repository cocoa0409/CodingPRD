"""Cross-entity cascades (fulfill -> invoice -> exposure -> credit hold, and
the payment-waterfall release) and the order's parallel state dimensions."""
from test_helpers import (
    apply_payment,
    confirm_order,
    fulfill_order,
    get_customer,
    get_invoice,
    get_order,
    make_customer,
    make_cylinder,
    make_demurrage_rental,
    make_fulfilled_net30_order,
    make_order,
    make_product,
    pay_order,
    run_billing_cycle,
    set_clock,
    stage_order,
)


class TestFulfillInvoiceExposureHoldChain:
    def _setup_cascade(self):
        """NET30 customer (limit 42000) with a DEMURRAGE rental and a
        confirmed 4 x 10000 order; after the clock walks to 2026-11-01 a
        billing run posts a 2400-cent rental invoice."""
        set_clock("2026-08-01T00:00:00Z")
        customer = make_customer(account_no="ACC-TC1", name="Cascade Co",
                                 terms="NET30", credit_limit_cents=42000)
        product = make_product(sku="HG-TC1", name="Torch Kit",
                               category="HARDGOOD", retail_price_cents=10000,
                               stock=10)
        asset = make_cylinder(serial_no="CYL-TC1", gas_grade="ARGON",
                              size="MEDIUM")
        make_demurrage_rental(customer["id"], asset["id"],
                              start_date="2026-08-01", grace_days=5)
        order = make_order(customer["id"],
                           [{"product_id": product["id"], "qty": 4}])
        confirm_order(order["id"])
        set_clock("2026-11-01T00:00:00Z")
        return customer, order

    def test_billing_invoice_alone_stays_under_limit(self, api):
        """PRD §2.9: "When an invoice-creation event (an order fulfillment, a
        rental billing run, or a rental close-out) pushes the customer's
        `posted_exposure_cents` strictly above the account's
        `credit_limit_cents`, the customer's status flips from `ACTIVE` to
        `CREDIT_HOLD` automatically; landing exactly at the limit does not
        trigger the hold." The billing run posts floor(87/30) = 2 periods =
        2400, which is below 42000, so no hold fires yet.

        Design: Difficulty/transitive_cascade/fulfill_invoice_exposure_hold_chain
        """
        customer, _order = self._setup_cascade()
        run = run_billing_cycle()
        assert run["invoices_created"] == 1
        assert run["total_billed_cents"] == 2400, \
            "floor(87/30) = 2 complete 30-day periods x 1200"
        assert get_customer(customer["id"])["status"] == "ACTIVE", \
            "posted 2400 <= 42000 — strictly-above rule not met"

    def test_fulfill_posts_invoice_and_auto_holds_customer(self, api):
        """PRD §3.4: "That invoice creation is hop 1 of the credit cascade —
        it recomputes the customer's exposure figures (hop 2), and if the
        posted exposure has risen strictly above the credit limit the
        customer's status flips `ACTIVE` → `CREDIT_HOLD` automatically (hop
        3, per §2.9)." The 40000-cent order invoice lands on top of the
        2400-cent rental invoice: 42400 > 42000.

        Design: Difficulty/transitive_cascade/fulfill_invoice_exposure_hold_chain
        """
        customer, order = self._setup_cascade()
        run_billing_cycle()
        stage_order(order["id"])
        fulfilled = fulfill_order(order["id"])
        assert fulfilled["payment_status"] == "INVOICED"
        invoice = get_invoice(fulfilled["invoice_id"])
        assert invoice["amount_cents"] == 40000
        assert invoice["source"] == "ORDER"
        account = get_customer(customer["id"])
        assert account["outstanding_balance_cents"] == 42400, \
            "hop 2: exposure recomputed as 2400 + 40000"
        assert account["status"] == "CREDIT_HOLD", \
            "hop 3: 42400 > 42000 auto-hold"


class TestPaymentWaterfallSettleReleaseChain:
    def _held_customer(self):
        """Fulfilled NET30 order (invoice I1 40000, due 08-31) plus a billing
        run at 2026-11-01 (invoice I2 2400) pushing posted exposure to 42400 >
        42000 -> CREDIT_HOLD."""
        set_clock("2026-08-01T00:00:00Z")
        customer = make_customer(account_no="ACC-TC2", name="Release Co",
                                 terms="NET30", credit_limit_cents=42000)
        product = make_product(sku="HG-TC2", name="Jacket XL",
                               category="HARDGOOD", retail_price_cents=10000,
                               stock=10)
        order = make_fulfilled_net30_order(customer["id"], product["id"], 4)
        asset = make_cylinder(serial_no="CYL-TC2", gas_grade="ARGON",
                              size="MEDIUM")
        make_demurrage_rental(customer["id"], asset["id"],
                              start_date="2026-08-01", grace_days=5)
        set_clock("2026-11-01T00:00:00Z")
        run_billing_cycle()
        return customer, order, order["invoice_id"]

    def test_billing_invoice_tips_customer_into_credit_hold(self, api):
        """PRD §2.9: "When an invoice-creation event (an order fulfillment, a
        rental billing run, or a rental close-out) pushes the customer's
        `posted_exposure_cents` strictly above the account's
        `credit_limit_cents`, the customer's status flips from `ACTIVE` to
        `CREDIT_HOLD` automatically". The rental invoice lifts the posted
        exposure from 40000 to 42400.

        Design: Difficulty/transitive_cascade/payment_waterfall_invoice_settle_release_chain
        """
        customer, _order, _inv1 = self._held_customer()
        account = get_customer(customer["id"])
        assert account["outstanding_balance_cents"] == 42400
        assert account["status"] == "CREDIT_HOLD"

    def test_payment_settles_invoices_and_releases_hold(self, api):
        """PRD §3.7: "An invoice reaching `PAID` fires the settlement cascade.
        If the invoice's `source` is `ORDER`, the linked order's
        `payment_status` moves `INVOICED` → `SETTLED`, incrementing the
        order's `version`." PRD §2.9: "Symmetrically, when a payment waterfall
        or an invoice void brings the posted exposure back down to at or below
        the limit, a customer sitting in `CREDIT_HOLD` is returned to `ACTIVE`
        automatically." A 42400-cent payment exactly covers 40000 + 2400.

        Design: Difficulty/transitive_cascade/payment_waterfall_invoice_settle_release_chain
        """
        customer, order, inv1 = self._held_customer()
        assert get_customer(customer["id"])["status"] == "CREDIT_HOLD"
        result = apply_payment(customer["id"], 42400)
        assert result["credit_added_cents"] == 0
        assert result["outstanding_balance_cents"] == 0
        assert get_invoice(inv1)["status"] == "PAID"
        assert get_order(order["id"])["payment_status"] == "SETTLED", \
            "invoice PAID cascades to the order's payment dimension"
        assert get_customer(customer["id"])["status"] == "ACTIVE", \
            "exposure 0 <= 42000 auto-releases the hold"


class TestOrderParallelDimensions:
    def test_cash_payment_moves_only_payment_dimension(self, api):
        """PRD §3.4: "A successful payment flips `payment_status` from
        `UNPAID` to `PAID` while the fulfillment dimension stays exactly where
        it was, and increments the order's `version`."

        Design: Difficulty/non_linear_state_machine/order_parallel_payment_fulfillment_dimensions
        """
        customer = make_customer(account_no="ACC-PD1", name="Cash Co",
                                 terms="CASH")
        product = make_product(sku="HG-PD1", name="Helmet",
                               category="HARDGOOD", retail_price_cents=10000,
                               stock=100)
        order = make_order(customer["id"],
                           [{"product_id": product["id"], "qty": 1}])
        confirm_order(order["id"])
        paid = pay_order(order["id"], 10000)
        assert paid["payment_status"] == "PAID"
        assert paid["fulfillment_status"] == "CONFIRMED", \
            "payment moved; fulfillment untouched"

    def test_net30_fulfill_then_waterfall_settle(self, api):
        """PRD §3.4: "For a `NET30` customer, fulfillment posts the order's
        invoice: an invoice is created with `source` `ORDER`, `amount_cents`
        equal to the order's `total_cents`, and `due_at` thirty days after
        issue; the order's `payment_status` moves `UNPAID` → `INVOICED` and
        its `invoice_id` is set to the new invoice." PRD §3.7: "If the
        invoice's `source` is `ORDER`, the linked order's `payment_status`
        moves `INVOICED` → `SETTLED`".

        Design: Difficulty/non_linear_state_machine/order_parallel_payment_fulfillment_dimensions
        """
        customer = make_customer(account_no="ACC-PD2", name="Terms Co",
                                 terms="NET30", credit_limit_cents=1000000)
        product = make_product(sku="HG-PD2", name="Helmet",
                               category="HARDGOOD", retail_price_cents=10000,
                               stock=100)
        order = make_order(customer["id"],
                           [{"product_id": product["id"], "qty": 1}])
        confirm_order(order["id"])
        stage_order(order["id"])
        fulfilled = fulfill_order(order["id"])
        assert fulfilled["fulfillment_status"] == "FULFILLED"
        assert fulfilled["payment_status"] == "INVOICED", \
            "fulfillment moved; payment dimension still open"
        assert fulfilled["invoice_id"]
        apply_payment(customer["id"], 10000)
        settled = get_order(order["id"])
        assert settled["payment_status"] == "SETTLED", \
            "waterfall settled the invoice, which settles the order"
        assert settled["fulfillment_status"] == "FULFILLED"
