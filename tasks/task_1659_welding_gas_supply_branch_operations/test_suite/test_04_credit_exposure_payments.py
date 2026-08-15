"""Credit exposure views, credit-limit boundary, payment waterfall, OCC on
payments, and invoice voiding."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    apply_payment,
    confirm_order,
    fulfill_order,
    get_customer,
    get_fresh_customer_version,
    get_invoice,
    get_order,
    make_customer,
    make_fulfilled_net30_order,
    make_order,
    make_product,
    set_clock,
    stage_order,
    validate_error,
    validate_success,
)

COUNTER_HEADERS = TEST_USERS["counter_rep_headers"]
MANAGER_HEADERS = TEST_USERS["branch_manager_headers"]


def cancel_order(order_id):
    return validate_success(api_client.cancel_order(order_id,
                                                    COUNTER_HEADERS))


class TestProjectedVsPostedExposure:
    def _confirmed_net30_order(self):
        customer = make_customer(account_no="ACC-EX1", name="Exposure Co",
                                 terms="NET30", credit_limit_cents=1000000)
        product = make_product(sku="HG-EX1", name="Welding Gloves",
                               category="HARDGOOD", retail_price_cents=10000,
                               stock=100)
        order = make_order(customer["id"],
                           [{"product_id": product["id"], "qty": 2}])
        return customer, product, confirm_order(order["id"])

    def test_projected_diverges_from_posted_while_order_open(self, api):
        """PRD §2.9: "`posted_exposure_cents` is the credit-managed view: the
        outstanding balance minus the credit balance, floored at zero." and
        "Finally, `projected_exposure_cents` is the forward-looking
        credit-check view: the posted exposure plus the accrued rental figure
        plus the sum of `total_cents` over the customer's orders whose
        `fulfillment_status` is `CONFIRMED` or `STAGED`."

        Design: Difficulty/dual_variant_calc/customer_exposure_projected_vs_posted
        """
        customer, _product, order = self._confirmed_net30_order()
        assert order["total_cents"] == 20000
        account = get_customer(customer["id"])
        assert account["posted_exposure_cents"] == 0, \
            "no invoice posted yet — the ledger view stays at zero"
        assert account["projected_exposure_cents"] == 20000, \
            "the CONFIRMED order total feeds only the forward-looking view"

    def test_views_reconverge_after_fulfillment_posts_invoice(self, api):
        """PRD §3.4: "For a `NET30` customer, fulfillment posts the order's
        invoice: an invoice is created with `source` `ORDER`, `amount_cents`
        equal to the order's `total_cents`, and `due_at` thirty days after
        issue". PRD §2.9: "`outstanding_balance_cents` is the plain ledger
        view: the sum, over the customer's invoices in `OPEN` status, of each
        invoice's `amount_cents` minus its `paid_cents`." Once the invoice
        replaces the open-order commitment, both exposure views read 20000.

        Design: Difficulty/dual_variant_calc/customer_exposure_projected_vs_posted
        """
        customer, _product, order = self._confirmed_net30_order()
        stage_order(order["id"])
        fulfill_order(order["id"])
        account = get_customer(customer["id"])
        assert account["posted_exposure_cents"] == 20000
        assert account["projected_exposure_cents"] == 20000, \
            "FULFILLED orders leave the projected sum; the OPEN invoice carries it"
        assert account["outstanding_balance_cents"] == 20000


class TestCreditLimitBoundary:
    def _customer_and_product(self):
        customer = make_customer(account_no="ACC-BP1", name="Boundary Co",
                                 terms="NET30", credit_limit_cents=50000)
        product = make_product(sku="HG-BP1", name="Regulator",
                               category="HARDGOOD", retail_price_cents=10000,
                               stock=10)
        return customer, product

    def test_confirm_at_exact_credit_limit_passes(self, api):
        """PRD §3.3: "Finally, for a `NET30` customer, confirmation runs the
        credit check: the customer's `projected_exposure_cents` plus the new
        order's `total_cents` must not exceed the account's
        `credit_limit_cents`; the comparison is strict, so landing exactly at
        the limit passes while one cent over is rejected with
        `ERR_CREDIT_LIMIT_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/credit_limit_equality_passes_then_one_order_over
        """
        customer, product = self._customer_and_product()
        order = make_order(customer["id"],
                           [{"product_id": product["id"], "qty": 5}])
        confirmed = confirm_order(order["id"])
        assert confirmed["fulfillment_status"] == "CONFIRMED"
        assert confirmed["total_cents"] == 50000, \
            "50000 > 50000 is false: equality passes"

    def test_one_order_over_the_limit_rejected(self, api,
                                               counter_rep_headers):
        """PRD §3.3: "the customer's `projected_exposure_cents` plus the new
        order's `total_cents` must not exceed the account's
        `credit_limit_cents`; the comparison is strict, so landing exactly at
        the limit passes while one cent over is rejected with
        `ERR_CREDIT_LIMIT_EXCEEDED`." After the 50000-cent order confirms, the
        next 10000-cent order pushes 60000 > 50000.

        Design: Difficulty/boundary_precision_check/credit_limit_equality_passes_then_one_order_over
        """
        customer, product = self._customer_and_product()
        first = make_order(customer["id"],
                           [{"product_id": product["id"], "qty": 5}])
        confirm_order(first["id"])
        second = make_order(customer["id"],
                            [{"product_id": product["id"], "qty": 1}])
        resp = api.confirm_order(second["id"], counter_rep_headers)
        validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED)


class TestConfirmBlockedByAccountStatus:
    def test_confirm_blocked_on_credit_hold(self, api, counter_rep_headers,
                                            branch_manager_headers):
        """PRD §3.1: "A customer in `CREDIT_HOLD` or `SUSPENDED` is blocked
        from order confirmation, rental opening, and enrollment creation with
        `ERR_ACCOUNT_ON_HOLD`." PRD §3.3: "The customer must be `ACTIVE`, or
        the confirm is rejected with `ERR_ACCOUNT_ON_HOLD`."

        Design: Difficulty/cross_entity_state_dependency/order_confirm_blocked_by_customer_credit_hold
        """
        customer = make_customer(account_no="ACC-XD1", name="Held Co",
                                 terms="NET30", credit_limit_cents=1000000)
        validate_success(api.credit_hold_action(
            customer["id"], {"action": "PLACE_HOLD"}, branch_manager_headers))
        product = make_product(sku="HG-XD1", name="Brush", category="HARDGOOD",
                               retail_price_cents=10000, stock=5)
        order = make_order(customer["id"],
                           [{"product_id": product["id"], "qty": 1}])
        resp = api.confirm_order(order["id"], counter_rep_headers)
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_ON_HOLD)

    def test_confirm_blocked_on_suspended(self, api, counter_rep_headers,
                                          branch_manager_headers):
        """PRD §3.1: "`SUSPEND` moves a customer from either `ACTIVE` or
        `CREDIT_HOLD` to `SUSPENDED`" and "A customer in `CREDIT_HOLD` or
        `SUSPENDED` is blocked from order confirmation, rental opening, and
        enrollment creation with `ERR_ACCOUNT_ON_HOLD`."

        Design: Difficulty/cross_entity_state_dependency/order_confirm_blocked_by_customer_credit_hold
        """
        customer = make_customer(account_no="ACC-XD1S", name="Suspended Co",
                                 terms="NET30", credit_limit_cents=1000000)
        validate_success(api.credit_hold_action(
            customer["id"], {"action": "SUSPEND"}, branch_manager_headers))
        product = make_product(sku="HG-XD1S", name="Brush",
                               category="HARDGOOD", retail_price_cents=10000,
                               stock=5)
        order = make_order(customer["id"],
                           [{"product_id": product["id"], "qty": 1}])
        resp = api.confirm_order(order["id"], counter_rep_headers)
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_ON_HOLD)


class TestStateBeatsFiscalOnConfirm:
    def _cancelled_order_over_limit(self):
        customer = make_customer(account_no="ACC-PP1", name="Conflict Co",
                                 terms="NET30", credit_limit_cents=10000)
        product = make_product(sku="HG-PP1", name="Clamp Set",
                               category="HARDGOOD", retail_price_cents=10000,
                               stock=10)
        order = make_order(customer["id"],
                           [{"product_id": product["id"], "qty": 2}])
        cancel_order(order["id"])
        return customer, product, order

    def test_cancelled_order_confirm_reports_invalid_state_not_credit(
            self, api, counter_rep_headers):
        """PRD §2.8: "A single request can violate several rules at once, so
        the API evaluates its checks as an ordered cascade of gates and
        reports the first gate that fails. The order below is normative:" —
        gate "6. **Target state.**" precedes gate "11. **Fiscal rules.** The
        NET30 credit check at confirmation (`ERR_CREDIT_LIMIT_EXCEEDED`)";
        and "a credit-limit failure on an otherwise valid confirmation
        surfaces only after every state, safety, temporal, and capacity gate
        has passed." Here the order is CANCELLED (state failure) and the
        20000-cent total also breaches the 10000-cent credit limit.

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_confirm
        """
        _customer, _product, order = self._cancelled_order_over_limit()
        resp = api.confirm_order(order["id"], counter_rep_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_each_gate_fires_in_isolation(self, api, counter_rep_headers):
        """PRD §2.8: gate "6. **Target state.** The target entity's own state
        permits the requested transition ... Violations are
        `ERR_INVALID_STATE`." fires alone when credit is ample, and gate "11.
        **Fiscal rules.** The NET30 credit check at confirmation
        (`ERR_CREDIT_LIMIT_EXCEEDED`)" fires alone when the order is a valid
        DRAFT — the two isolated outcomes the ordered cascade compresses into
        the single state error when both fail at once.

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_confirm
        """
        # State leg alone: cancelled order, but credit cannot fail (CASH).
        cash = make_customer(account_no="ACC-PP1B", name="Cash Co",
                             terms="CASH")
        product = make_product(sku="HG-PP1B", name="Clamp Set",
                               category="HARDGOOD", retail_price_cents=10000,
                               stock=10)
        order = make_order(cash["id"],
                           [{"product_id": product["id"], "qty": 2}])
        cancel_order(order["id"])
        resp = api.confirm_order(order["id"], counter_rep_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        # Fiscal leg alone: DRAFT order, projected 0 + 20000 > 10000.
        net = make_customer(account_no="ACC-PP1C", name="Fiscal Co",
                            terms="NET30", credit_limit_cents=10000)
        order2 = make_order(net["id"],
                            [{"product_id": product["id"], "qty": 2}])
        resp2 = api.confirm_order(order2["id"], counter_rep_headers)
        validate_error(resp2, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED)


class TestPaymentWaterfallConservation:
    def _three_invoice_customer(self):
        """Invoices: Ib 5000 (issued 08-01), Ic 5000 (issued 08-01),
        Ia 10000 (issued 08-05, due later)."""
        set_clock("2026-08-01T00:00:00Z")
        customer = make_customer(account_no="ACC-CI2", name="Waterfall Co",
                                 terms="NET30", credit_limit_cents=10000000)
        p10 = make_product(sku="HG-CI2A", name="Grinder", category="HARDGOOD",
                           retail_price_cents=10000, stock=5)
        p5 = make_product(sku="HG-CI2B", name="Disc Pack", category="HARDGOOD",
                          retail_price_cents=5000, stock=5)
        inv_b = make_fulfilled_net30_order(customer["id"], p5["id"], 1)[
            "invoice_id"]
        inv_c = make_fulfilled_net30_order(customer["id"], p5["id"], 1)[
            "invoice_id"]
        set_clock("2026-08-05T00:00:00Z")
        inv_a = make_fulfilled_net30_order(customer["id"], p10["id"], 1)[
            "invoice_id"]
        return customer, inv_b, inv_c, inv_a

    def test_waterfall_allocates_in_pinned_order_and_conserves_cash(self, api):
        """PRD §3.7: "The payment sweeps the customer's `OPEN` invoices — and
        only those; `PAID` and `VOID` invoices are never candidates — in a
        pinned order: earliest `due_at` first, ties broken by earliest
        `issued_at`, further ties by earliest `created_at`, and never by
        identifier." and "Allocation is exact: the sum of the per-invoice
        applications plus the credit added equals the payment amount to the
        cent." A 12000-cent payment covers Ib 5000 + Ic 5000 + Ia 2000 with
        nothing left over (5000 + 5000 + 2000 + 0 == 12000).

        Design: Difficulty/compensating_invariant/payment_waterfall_cash_conservation
        """
        customer, inv_b, inv_c, inv_a = self._three_invoice_customer()
        result = apply_payment(customer["id"], 12000)
        assert result["credit_added_cents"] == 0
        assert result["outstanding_balance_cents"] == 8000
        assert get_invoice(inv_b)["status"] == "PAID"
        assert get_invoice(inv_c)["status"] == "PAID", \
            "due_at tie between Ib and Ic broken by issue order; both paid"
        invoice_a = get_invoice(inv_a)
        assert invoice_a["status"] == "OPEN"
        assert invoice_a["paid_cents"] == 2000

    def test_overpayment_parks_as_credit_balance(self, api):
        """PRD §3.7: "Whatever remains after the sweep is added to the
        customer's `credit_balance_cents` as unapplied overpayment." and
        "Allocation is exact: the sum of the per-invoice applications plus the
        credit added equals the payment amount to the cent." After the first
        12000-cent sweep, a 99999-cent payment settles the last 8000 of Ia and
        parks 91999 as credit (8000 + 91999 == 99999).

        Design: Difficulty/compensating_invariant/payment_waterfall_cash_conservation
        """
        customer, _inv_b, _inv_c, inv_a = self._three_invoice_customer()
        apply_payment(customer["id"], 12000)
        result = apply_payment(customer["id"], 99999)
        assert result["credit_added_cents"] == 91999
        assert result["outstanding_balance_cents"] == 0
        assert get_invoice(inv_a)["status"] == "PAID"
        assert get_customer(customer["id"])["credit_balance_cents"] == 91999


class TestPaymentOptimisticConcurrency:
    def test_stale_customer_version_rejected(self, api, counter_rep_headers):
        """PRD §2.7: "Applying a payment to a customer account requires a
        non-optional `expected_customer_version` field carrying the customer's
        `version` as the client last observed it. If the customer's current
        `version` no longer matches — because an invoice was created, an
        earlier payment landed, or a credit-hold action ran in between — the
        request is rejected with `ERR_STALE_VERSION` (HTTP 412)." PRD §3.7:
        "Whatever remains after the sweep is added to the customer's
        `credit_balance_cents` as unapplied overpayment."

        Design: Corner/cross_cutting_layers/occ_payment_stale_customer_version_rejected
        """
        customer = make_customer(account_no="ACC-LA1", name="OCC Co",
                                 terms="CASH")
        version = get_fresh_customer_version(customer["id"])
        first = validate_success(api.apply_payment(
            customer["id"],
            {"amount_cents": 1000, "expected_customer_version": version},
            counter_rep_headers))
        assert first["credit_added_cents"] == 1000, \
            "no open invoices — the whole payment parks as credit"
        replay = api.apply_payment(
            customer["id"],
            {"amount_cents": 500, "expected_customer_version": version},
            counter_rep_headers)
        validate_error(replay, ApiErrorId.ERR_STALE_VERSION, 412)


class TestInvoiceVoiding:
    def _net30_invoice(self, account_no, sku):
        customer = make_customer(account_no=account_no, name="Void Co",
                                 terms="NET30", credit_limit_cents=1000000)
        product = make_product(sku=sku, name="Rod Oven", category="HARDGOOD",
                               retail_price_cents=10000, stock=1)
        order = make_fulfilled_net30_order(customer["id"], product["id"], 1)
        return customer, order, order["invoice_id"]

    def test_void_after_partial_payment_rejected(self, api,
                                                 branch_manager_headers):
        """PRD §3.7: "It is permitted only while the invoice is `OPEN` and its
        `paid_cents` is still 0; an attempt against an invoice that has
        collected any payment, or that has already left `OPEN`, is rejected
        with `ERR_INVOICE_NOT_VOIDABLE`."

        Design: Corner/state_machines/invoice_void_after_partial_payment_rejected
        """
        customer, _order, invoice_id = self._net30_invoice("ACC-SM5",
                                                           "HG-SM5")
        apply_payment(customer["id"], 4000)
        resp = api.void_invoice(invoice_id, branch_manager_headers)
        validate_error(resp, ApiErrorId.ERR_INVOICE_NOT_VOIDABLE)

    def test_void_reverts_order_payment_and_exposure(self, api,
                                                     branch_manager_headers):
        """PRD §3.7: "A void drops the balance out of the customer's exposure
        figures — which may release a credit hold — and, when the voided
        invoice's `source` is `ORDER`, reverts the linked order's
        `payment_status` from `INVOICED` back to `UNPAID`. The invoice lands
        in the terminal `VOID` state with its `version` incremented."

        Design: Corner/validations/invoice_void_reverts_order_payment_and_exposure
        """
        customer, order, invoice_id = self._net30_invoice("ACC-VA17",
                                                          "HG-VA17")
        voided = validate_success(api.void_invoice(invoice_id,
                                                   branch_manager_headers))
        assert voided["status"] == "VOID"
        assert get_order(order["id"])["payment_status"] == "UNPAID", \
            "ORDER-sourced void reverts the payment dimension"
        assert get_customer(customer["id"])["outstanding_balance_cents"] == 0, \
            "VOID invoices leave the open balance"

    def test_trainer_cannot_void_invoice(self, api, trainer_headers):
        """PRD §2.1: "A request whose role is recognized but is not listed for
        the endpoint — or that fails a per-action role condition, such as the
        fulfillment-type split on order fulfillment or the per-target role
        split on repair-ticket and enrollment advancement described in §3 — is
        rejected with `ERR_FORBIDDEN` (HTTP 403)." PRD §4 lists POST
        /invoices/{id}/void under BranchManager only.

        Design: Corner/rbac/trainer_cannot_void_invoice
        """
        _customer, _order, invoice_id = self._net30_invoice("ACC-RB3",
                                                            "HG-RB3")
        resp = api.void_invoice(invoice_id, trainer_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)
