"""Money pipeline: delivery opens the invoice, FIFO payment application,
overpayment caps, NSF returns, and the two parallel status dimensions."""
from test_helpers import (
    CREDIT_MANAGER,
    DISPATCHER,
    ApiErrorId,
    api_client,
    assert_dealer_payment,
    base_order_fixture,
    create_order,
    drive_order_to_delivered,
    get_success_data,
    make_dealer_user_headers,
    post_payment,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


def _setup_delivered_order(name="T-S1", requested_gal=9_000, **kwargs):
    """FIXED-contract order driven to DELIVERED (invoice OPEN).

    9000 gal at 90000 mc: rhu(810000) + max(150000, 72000) = 960000 cents.
    """
    ctx = base_order_fixture(name=name, **kwargs)
    order = create_order(ctx["dealer"]["id"], ctx["terminal"]["id"],
                         ctx["zone"]["id"], requested_gal,
                         dealer_contract_id=ctx["dealer_contract"]["id"])
    drive_order_to_delivered(order["id"], ctx["trucks"][0]["id"])
    delivered = get_success_data(api_client.get_delivery_order(order["id"],
                                                               DISPATCHER))
    assert delivered["fulfillment_status"] == "DELIVERED"
    assert delivered["invoice_status"] == "OPEN", "setup check: invoice opened"
    return ctx, delivered


class TestParallelDimensions:

    def test_payment_flips_invoice_while_fulfillment_stays_delivered(self):
        """PRD section 3.9: "Throughout, the two status dimensions of a
        delivery order evolve independently: `fulfillment_status` walks the
        physical pipeline while `invoice_status` walks the money pipeline, and
        neither implies the other except at the two bridges — delivery opens
        the invoice, and pre-delivery cancellation voids it."
        PRD section 3.8: "any order whose balance reaches zero moves from
        `OPEN` to `PAID`."

        Design: Difficulty/non_linear_state_machine/delivery_order_parallel_dimensions_independent
        """
        ctx, order = _setup_delivered_order()
        assert order["open_balance_cents"] == 960_000

        post_payment(ctx["dealer"]["id"], 960_000, method="ACH")
        mid = get_success_data(api_client.get_delivery_order(order["id"],
                                                             DISPATCHER))
        assert mid["invoice_status"] == "PAID"
        assert mid["fulfillment_status"] == "DELIVERED", \
            "the physical axis does not move when the money axis cycles"

    def test_return_reopens_invoice_while_fulfillment_stays_delivered(self):
        """PRD section 3.8: "The return reverses this payment's applications in
        reverse application order: each order's `open_balance_cents` is
        increased by its reversed slice, and an order whose balance is restored
        above zero moves from `PAID` back to `OPEN`."
        PRD section 3.9: "the two status dimensions of a delivery order evolve
        independently"

        Design: Difficulty/non_linear_state_machine/delivery_order_parallel_dimensions_independent
        """
        ctx, order = _setup_delivered_order()
        payment = post_payment(ctx["dealer"]["id"], 960_000, method="ACH")
        api_client.return_dealer_payment(payment["id"], CREDIT_MANAGER)

        end = get_success_data(api_client.get_delivery_order(order["id"],
                                                             DISPATCHER))
        assert end["invoice_status"] == "OPEN"
        assert end["open_balance_cents"] == 960_000, \
            "the reversed slice restores the full balance"
        assert end["fulfillment_status"] == "DELIVERED", \
            "fulfillment never left DELIVERED across both invoice flips"


class TestFifoApplication:

    def test_fifo_payment_oldest_invoice_first(self):
        """PRD section 3.8: "On posting, the payment is `POSTED` and is applied
        FIFO: the dealer's orders with `invoice_status` `OPEN` are visited in
        `invoiced_at` order, earliest first, ties broken by `created_at`; each
        receives a slice of the smaller of the remaining payment and that
        order's `open_balance_cents`, the slice is recorded in the payment's
        `applications` in application order as `order_id` and `amount_cents`
        pairs, and any order whose balance reaches zero moves from `OPEN` to
        `PAID`."

        Design: Corner/calculations/fifo_payment_oldest_invoice_first
        """
        ctx = base_order_fixture(name="T-L3")
        dealer = ctx["dealer"]
        order_a = create_order(dealer["id"], ctx["terminal"]["id"],
                               ctx["zone"]["id"], 9_000,
                               dealer_contract_id=ctx["dealer_contract"]["id"])
        drive_order_to_delivered(order_a["id"], ctx["trucks"][0]["id"],
                                 "2026-08-03T08:00:00Z", "2026-08-03T10:00:00Z")
        order_b = create_order(dealer["id"], ctx["terminal"]["id"],
                               ctx["zone"]["id"], 5_000,
                               dealer_contract_id=ctx["dealer_contract"]["id"])
        drive_order_to_delivered(order_b["id"], ctx["trucks"][0]["id"],
                                 "2026-08-04T08:00:00Z", "2026-08-04T10:00:00Z")
        # Invoices: A 960000 (earlier invoiced_at), B 600000.

        resp = api_client.create_dealer_payment(
            {"dealer_id": dealer["id"], "amount_cents": 1_000_000,
             "method": "ACH"},
            CREDIT_MANAGER,
        )
        payment = validate_success(resp, expected_status=201)
        assert_dealer_payment(payment)
        assert payment["applications"] == [
            {"order_id": order_a["id"], "amount_cents": 960_000},
            {"order_id": order_b["id"], "amount_cents": 40_000},
        ], "the oldest invoice is paid off before the newer one is touched"

        a = get_success_data(api_client.get_delivery_order(order_a["id"],
                                                           CREDIT_MANAGER))
        assert a["invoice_status"] == "PAID"
        assert a["open_balance_cents"] == 0
        b = get_success_data(api_client.get_delivery_order(order_b["id"],
                                                           CREDIT_MANAGER))
        assert b["invoice_status"] == "OPEN"
        assert b["open_balance_cents"] == 560_000

    def test_overpayment_rejected(self):
        """PRD section 3.8: "The amount must not exceed the dealer's total open
        invoice balance — the `ledger_exposure_cents` — or posting is rejected
        with `ERR_OVERPAYMENT`."

        Design: Corner/validations/overpayment_rejected
        """
        ctx, order = _setup_delivered_order(name="T-V7")
        resp = api_client.create_dealer_payment(
            {"dealer_id": ctx["dealer"]["id"], "amount_cents": 960_001,
             "method": "ACH"},
            CREDIT_MANAGER,
        )
        validate_error(resp, ApiErrorId.ERR_OVERPAYMENT)

        after = get_success_data(api_client.get_delivery_order(order["id"],
                                                               CREDIT_MANAGER))
        assert after["open_balance_cents"] == 960_000, \
            "one cent over the open balance rejects the whole payment"


class TestPaymentReturn:

    def test_payment_double_return_rejected(self):
        """PRD section 3.8: "Only a `POSTED` payment can be returned; a second
        attempt fails with `ERR_PAYMENT_ALREADY_RETURNED`."

        Design: Corner/state_machines/payment_double_return_rejected
        """
        ctx, _ = _setup_delivered_order(name="T-M9")
        payment = post_payment(ctx["dealer"]["id"], 960_000, method="ACH")
        api_client.return_dealer_payment(payment["id"], CREDIT_MANAGER)
        fee_after_first = get_success_data(api_client.get_dealer(
            ctx["dealer"]["id"], CREDIT_MANAGER))["fee_balance_cents"]

        resp = api_client.return_dealer_payment(payment["id"], CREDIT_MANAGER)
        validate_error(resp, ApiErrorId.ERR_PAYMENT_ALREADY_RETURNED)

        fee_after_second = get_success_data(api_client.get_dealer(
            ctx["dealer"]["id"], CREDIT_MANAGER))["fee_balance_cents"]
        assert fee_after_second == fee_after_first, \
            "a rejected second return must not post the fee twice"
        assert fee_after_first > 0, \
            "setup check: the first return posted the insufficient-funds fee"

    def test_payment_post_return_conserves_ledger_exposure(self):
        """PRD section 3.8: "The return reverses this payment's applications in
        reverse application order: each order's `open_balance_cents` is
        increased by its reversed slice, and an order whose balance is restored
        above zero moves from `PAID` back to `OPEN`."
        PRD section 3.3: "The `ledger_exposure_cents` is the backward-looking
        view: the sum of `open_balance_cents` over the dealer's orders whose
        `invoice_status` is `OPEN`."

        Design: Difficulty/compensating_invariant/payment_post_return_conserves_ledger_exposure
        """
        ctx, _ = _setup_delivered_order(name="T-I2")

        def ledger():
            return get_success_data(api_client.get_dealer(
                ctx["dealer"]["id"], CREDIT_MANAGER))["ledger_exposure_cents"]

        assert ledger() == 960_000
        payment = post_payment(ctx["dealer"]["id"], 960_000, method="CHECK")
        assert ledger() == 0, "the full payment zeroes the open balance"
        api_client.return_dealer_payment(payment["id"], CREDIT_MANAGER)
        assert ledger() == 960_000, \
            "post + return conserves the ledger exposure exactly"

    def test_return_fee_lives_outside_the_ledger(self):
        """PRD section 3.8: "The dealer's `fee_balance_cents` increases by a
        fixed insufficient-funds fee, bumping `Dealer.version`"
        PRD section 3.3: "The `ledger_exposure_cents` is ... the sum of
        `open_balance_cents` over the dealer's orders whose `invoice_status` is
        `OPEN`." — the fee is not an invoice balance.

        Design: Difficulty/compensating_invariant/payment_post_return_conserves_ledger_exposure
        """
        ctx, _ = _setup_delivered_order(name="T-I2")
        dealer_id = ctx["dealer"]["id"]
        before = get_success_data(api_client.get_dealer(dealer_id,
                                                        CREDIT_MANAGER))
        payment = post_payment(dealer_id, 960_000, method="CHECK")
        api_client.return_dealer_payment(payment["id"], CREDIT_MANAGER)

        after = get_success_data(api_client.get_dealer(dealer_id,
                                                       CREDIT_MANAGER))
        assert after["fee_balance_cents"] > 0, \
            "the return posts a fixed insufficient-funds fee"
        assert after["ledger_exposure_cents"] == 960_000, \
            "the fee never contaminates the invoice-balance ledger"
        assert after["version"] > before["version"] + 0 and \
            after["version"] != before["version"], \
            "the fee posting bumps Dealer.version"


class TestReturnDrivenCreditCascade:

    def _setup_paid_in_full(self):
        """Dealer limit 1683500; 17000-gal FIXED order DELIVERED (invoice
        1680000); payment of 1680000 POSTED so the invoice is PAID."""
        # 17000 gal must fit the truck's tank (PRD 3.6 capacity gate).
        ctx = base_order_fixture(name="T-K2", credit_limit_cents=1_683_500,
                                 truck_capacity_gal=20_000)
        order = create_order(ctx["dealer"]["id"], ctx["terminal"]["id"],
                             ctx["zone"]["id"], 17_000,
                             dealer_contract_id=ctx["dealer_contract"]["id"])
        drive_order_to_delivered(order["id"], ctx["trucks"][0]["id"])
        payment = post_payment(ctx["dealer"]["id"], 1_680_000, method="ACH")
        return ctx, order, payment

    def test_return_restores_invoice_and_posts_fee(self):
        """PRD section 3.8: "The return reverses this payment's applications in
        reverse application order: each order's `open_balance_cents` is
        increased by its reversed slice, and an order whose balance is restored
        above zero moves from `PAID` back to `OPEN`. The dealer's
        `fee_balance_cents` increases by a fixed insufficient-funds fee,
        bumping `Dealer.version`, and the dealer's exposure and credit posture
        are recomputed"

        Design: Difficulty/transitive_cascade/payment_return_reverses_invoices_to_suspension
        """
        ctx, order, payment = self._setup_paid_in_full()
        dealer_id = ctx["dealer"]["id"]

        paid = get_success_data(api_client.get_dealer(dealer_id,
                                                      CREDIT_MANAGER))
        assert paid["credit_status"] == "GOOD_STANDING", \
            "setup check: fully paid exposure leaves the dealer in good standing"
        invoice = get_success_data(api_client.get_delivery_order(order["id"],
                                                                 CREDIT_MANAGER))
        assert invoice["invoice_status"] == "PAID"

        api_client.return_dealer_payment(payment["id"], CREDIT_MANAGER)

        restored = get_success_data(api_client.get_delivery_order(order["id"],
                                                                  CREDIT_MANAGER))
        assert restored["invoice_status"] == "OPEN"
        assert restored["open_balance_cents"] == 1_680_000

        dealer = get_success_data(api_client.get_dealer(dealer_id,
                                                        CREDIT_MANAGER))
        assert dealer["fee_balance_cents"] > 0, \
            "the insufficient-funds fee is posted on the return"

    def test_order_after_return_is_rejected_by_credit(self):
        """PRD section 3.8: "the dealer's exposure and credit posture are
        recomputed — a dealer may slide from `WATCH` into `SUSPENDED` on the
        strength of a return."
        PRD section 3.4: "a `SUSPENDED` dealer is rejected here with
        `ERR_DEALER_SUSPENDED` and never reaches pricing." and "if
        `committed_before` plus the order's provisional total exceeds
        `credit_limit_cents`, creation is rejected with
        `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402)." — after the return restores
        1680000 of exposure against a 1683500 limit, a new 5000-gal order
        (provisional 600000) is rejected at one of these two credit layers
        depending on where the recomputed posture lands.

        Design: Difficulty/transitive_cascade/payment_return_reverses_invoices_to_suspension
        """
        ctx, _, payment = self._setup_paid_in_full()
        api_client.return_dealer_payment(payment["id"], CREDIT_MANAGER)

        resp = api_client.create_delivery_order(
            {"dealer_contract_id": ctx["dealer_contract"]["id"],
             "terminal_id": ctx["terminal"]["id"],
             "freight_zone_id": ctx["zone"]["id"], "requested_gal": 5_000},
            make_dealer_user_headers(ctx["dealer"]["id"]),
        )
        actual = validate_error_is_one_of(
            resp, [ApiErrorId.ERR_DEALER_SUSPENDED,
                   ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED])
        assert actual in (ApiErrorId.ERR_DEALER_SUSPENDED.value,
                          ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED.value)
        assert resp.status_code in (402, 409)
