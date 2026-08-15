"""Payments, refunds, and write-offs: the parallel payment/fulfillment
dimensions of an invoice, the conserved money ledger, the refund
compensation cascade, winner-cardinality conservation, and eligibility
gates."""
from test_helpers import (
    ADMIN,
    FO,
    ApiErrorId,
    api_client,
    assert_invoice,
    close_bidding,
    create_bidder,
    get_certificate_for_invoice,
    get_disposition_for_item,
    get_invoice_for_bundle,
    get_success_data,
    make_bidder_headers,
    pay_invoice_in_full,
    place_bid,
    setup_bidding_open_scenario,
    setup_paid_scenario,
    setup_sold_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)


def _pay(invoice_id, amount, bidder_id, method="CARD"):
    resp = api_client.create_payment(
        invoice_id, {"amount_cents": amount, "method": method},
        make_bidder_headers(bidder_id))
    return validate_success(resp, expected_status=201)


def _settle(payment_id, outcome="SUCCEEDED"):
    return validate_success(api_client.simulate_payment(
        {"payment_id": payment_id, "outcome": outcome}, ADMIN))


class TestParallelPaymentFulfillmentDimensions:

    def test_partial_payment_moves_payment_status_only(self):
        """PRD section 3.7: "A success recomputes the invoice's
        `amount_paid_cents` and may advance its `payment_status`: a
        payment covering less than the outstanding balance moves an
        `UNPAID` invoice to `PARTIALLY_PAID`"

        Design: Difficulty/non_linear_state_machine/invoice_parallel_payment_fulfillment_dimensions
        """
        ctx = setup_sold_scenario(fmv_cents=40000, bid_amount=50000,
                                  kind="EXPERIENCE")
        invoice_id = ctx["invoice"]["id"]
        payment = _pay(invoice_id, 20000, ctx["bidder"]["id"])
        _settle(payment["id"])

        invoice = get_success_data(api_client.get_invoice(invoice_id, FO))
        assert invoice["payment_status"] == "PARTIALLY_PAID", \
            "payment dimension moved"
        assert invoice["fulfillment_status"] == "PENDING", \
            "fulfillment dimension stays put"
        assert invoice["amount_paid_cents"] == 20000

    def test_full_payment_and_redemption_move_each_dimension_once(self):
        """PRD section 3.7: "one covering the full outstanding balance
        moves an `UNPAID` or `PARTIALLY_PAID` invoice to `PAID` and fires
        the paid cascade — `fulfillment_status` moves from `PENDING` to
        `READY`, and the invoice's certificate, if any, moves from
        `PENDING_ISSUE` to `ISSUED` with its validity window populated as
        §3.8 describes." PRD section 3.8: "moves the certificate from
        `ISSUED` to `REDEEMED`, moves the invoice's `fulfillment_status`
        from `READY` to `FULFILLED`"

        Design: Difficulty/non_linear_state_machine/invoice_parallel_payment_fulfillment_dimensions
        """
        ctx = setup_sold_scenario(fmv_cents=40000, bid_amount=50000,
                                  kind="EXPERIENCE")
        invoice_id = ctx["invoice"]["id"]
        p1 = _pay(invoice_id, 20000, ctx["bidder"]["id"])
        _settle(p1["id"])
        p2 = _pay(invoice_id, 30000, ctx["bidder"]["id"], method="CHECK")
        _settle(p2["id"])

        invoice = get_success_data(api_client.get_invoice(invoice_id, FO))
        assert invoice["payment_status"] == "PAID"
        assert invoice["fulfillment_status"] == "READY"
        assert invoice["amount_paid_cents"] == 50000

        cert = get_certificate_for_invoice(invoice_id)
        assert cert["status"] == "ISSUED"
        assert cert["issued_at"] == "2026-08-01T00:00:00Z"
        assert cert["valid_from"] == "2026-08-01T00:00:00Z"
        assert cert["expires_at"] == "2027-08-01T00:00:00Z", \
            "issued_at + 12 calendar months"
        assert cert["grace_end_at"] == "2027-08-31T00:00:00Z", \
            "expires_at + 30 grace days"

        redeemed = validate_success(api_client.redeem_certificate(
            cert["id"],
            {"scheduled_start": "2027-01-10T00:00:00Z",
             "scheduled_end": "2027-01-12T00:00:00Z"},
            make_bidder_headers(ctx["bidder"]["id"]),
        ))
        assert redeemed["status"] == "REDEEMED"

        invoice = get_success_data(api_client.get_invoice(invoice_id, FO))
        assert invoice["fulfillment_status"] == "FULFILLED", \
            "fulfillment moved alone"
        assert invoice["payment_status"] == "PAID"
        assert invoice["amount_paid_cents"] == 50000


class TestMoneyConservation:

    def test_pay_then_refund_restores_amount_paid(self):
        """PRD section 3.7: "An invoice's `amount_paid_cents` is the sum
        of the `amount_cents` of its `SUCCEEDED` payments minus the sum of
        the `amount_cents` of its `REFUNDED` payments; `INITIATED` and
        `FAILED` payments are excluded." and "a succeeded payment followed
        by its refund restores `amount_paid_cents` to its pre-payment
        value."

        Design: Difficulty/compensating_invariant/payment_refund_money_conservation
        """
        ctx = setup_paid_scenario(fmv_cents=40000, bid_amount=50000)
        invoice_id = ctx["invoice"]["id"]

        before_summary = get_success_data(
            api_client.get_event_summary(ctx["event"]["id"], FO))
        assert before_summary["collected_cents"] == 50000
        assert before_summary["recognized_revenue_cents"] == 40000
        assert before_summary["recognized_contribution_cents"] == 10000

        validate_success(api_client.refund_invoice(invoice_id, FO))
        invoice = get_success_data(api_client.get_invoice(invoice_id, FO))
        assert invoice["amount_paid_cents"] == 0, \
            "pre-payment value restored"
        assert invoice["payment_status"] == "REFUNDED"

    def test_refund_zeroes_recognition_in_summary(self):
        """PRD section 3.9: "`collected_cents`, the sum of
        `amount_paid_cents` over those invoices" and
        "`recognized_revenue_cents`, the sum of `revenue_portion_cents`
        over invoices with `payment_status` `PAID` only" and
        "`refunded_cents`, the same sum over invoices with
        `payment_status` `REFUNDED`".

        Design: Difficulty/compensating_invariant/payment_refund_money_conservation
        """
        ctx = setup_paid_scenario(fmv_cents=40000, bid_amount=50000)
        validate_success(
            api_client.refund_invoice(ctx["invoice"]["id"], FO))
        summary = get_success_data(
            api_client.get_event_summary(ctx["event"]["id"], FO))
        assert summary["collected_cents"] == 0
        assert summary["refunded_cents"] == 50000
        assert summary["recognized_revenue_cents"] == 0, \
            "REFUNDED excluded from the PAID-only aggregates"
        assert summary["recognized_contribution_cents"] == 0


class TestRefundCompensationCascade:

    def test_refund_cascade_invoice_side(self):
        """PRD section 3.7: "The refund cascade then moves every
        `SUCCEEDED` payment of the invoice to `REFUNDED` (so
        `amount_paid_cents` recomputes to zero), moves
        `fulfillment_status` to `VOIDED`, moves a certificate in
        `PENDING_ISSUE` or `ISSUED` to `VOIDED`"

        Design: Difficulty/transitive_cascade/refund_compensation_cascade
        """
        ctx = setup_paid_scenario(fmv_cents=40000, bid_amount=50000,
                                  kind="EXPERIENCE")
        invoice_id = ctx["invoice"]["id"]
        validate_success(api_client.refund_invoice(invoice_id, FO))

        invoice = get_success_data(api_client.get_invoice(invoice_id, FO))
        assert invoice["payment_status"] == "REFUNDED"
        assert invoice["fulfillment_status"] == "VOIDED"
        assert invoice["amount_paid_cents"] == 0

        payments, _m = validate_paginated(
            api_client.list_invoice_payments(invoice_id, FO))
        assert len(payments) == 1
        assert payments[0]["status"] == "REFUNDED", \
            "hop: invoice -> payments"

        certs, _m2 = validate_paginated(
            api_client.list_invoice_certificates(invoice_id, FO))
        assert certs[0]["status"] == "VOIDED", \
            "hop: invoice -> certificate"

    def test_refund_cascade_catalog_side(self):
        """PRD section 3.7: "moves the `WINNER` bid to `VOID`, moves the
        bundle from `SOLD` back to `UNSOLD`, moves every member item from
        `SOLD` to `UNSOLD`, and creates one disposition in `PROPOSED`
        status per member item."

        Design: Difficulty/transitive_cascade/refund_compensation_cascade
        """
        ctx = setup_paid_scenario(fmv_cents=40000, bid_amount=50000,
                                  kind="EXPERIENCE")
        validate_success(
            api_client.refund_invoice(ctx["invoice"]["id"], FO))

        bids, _m = validate_paginated(
            api_client.list_bundle_bids(ctx["bundle"]["id"], ADMIN))
        assert bids[0]["status"] == "VOID", "hop: invoice -> bid"

        bundle = get_success_data(
            api_client.get_bundle(ctx["bundle"]["id"], ADMIN))
        assert bundle["status"] == "UNSOLD", "hop: bid -> bundle"

        item = get_success_data(
            api_client.get_item(ctx["items"][0]["id"], ADMIN))
        assert item["status"] == "UNSOLD", "hop: bundle -> item"

        disposition = get_disposition_for_item(ctx["items"][0]["id"])
        assert disposition["status"] == "PROPOSED", "terminal hop"


class TestWinnerCardinalityConservation:

    def _two_bid_paid_sale(self):
        """Two bids (50000 then 55000) on one PHYSICAL bundle (FMV 40000);
        the event closes with the second bid winning and the invoice is
        paid in full."""
        ctx = setup_bidding_open_scenario(fmv_cents=40000, title="Sofa")
        bidder1 = create_bidder(ctx["event"]["id"], full_name="Bidder One")
        bidder2 = create_bidder(ctx["event"]["id"], full_name="Bidder Two")
        bid1 = place_bid(ctx["bundle"]["id"], 50000, bidder1["id"])
        bid2 = place_bid(ctx["bundle"]["id"], 55000, bidder2["id"])
        close_bidding(ctx["event"]["id"])
        invoice = get_invoice_for_bundle(ctx["bundle"]["id"])
        pay_invoice_in_full(invoice, bidder2["id"])
        ctx.update({"bidder1": bidder1, "bidder2": bidder2,
                    "bid1": bid1, "bid2": bid2, "invoice": invoice})
        return ctx

    def test_winner_cardinality_after_close(self):
        """PRD section 3.5: "Because every accepted bid strictly exceeds
        the previous high, at most one `ACTIVE` bid exists per bundle at
        any moment — and that single `ACTIVE` bid is the one the close
        cascade of §3.6 crowns as `WINNER`."

        Design: Difficulty/compensating_invariant/winner_cardinality_conservation_across_refund
        """
        ctx = self._two_bid_paid_sale()
        bids, _m = validate_paginated(
            api_client.list_bundle_bids(ctx["bundle"]["id"], ADMIN))
        by_id = {b["id"]: b for b in bids}
        assert by_id[ctx["bid1"]["id"]]["status"] == "OUTBID"
        assert by_id[ctx["bid2"]["id"]]["status"] == "WINNER"
        winners = [b for b in bids if b["status"] == "WINNER"]
        assert len(winners) == 1
        assert winners[0]["amount_cents"] == 55000

        bundle = get_success_data(
            api_client.get_bundle(ctx["bundle"]["id"], ADMIN))
        assert bundle["status"] == "SOLD"
        assert len(winners) == (1 if bundle["status"] == "SOLD" else 0)

    def test_winner_cardinality_restored_after_refund(self):
        """PRD section 3.7: "moves the `WINNER` bid to `VOID`, moves the
        bundle from `SOLD` back to `UNSOLD`"

        Design: Difficulty/compensating_invariant/winner_cardinality_conservation_across_refund
        """
        ctx = self._two_bid_paid_sale()
        validate_success(
            api_client.refund_invoice(ctx["invoice"]["id"], FO))

        bids, _m = validate_paginated(
            api_client.list_bundle_bids(ctx["bundle"]["id"], ADMIN))
        by_id = {b["id"]: b for b in bids}
        assert by_id[ctx["bid2"]["id"]]["status"] == "VOID"
        winners = [b for b in bids if b["status"] == "WINNER"]
        assert len(winners) == 0

        bundle = get_success_data(
            api_client.get_bundle(ctx["bundle"]["id"], ADMIN))
        assert bundle["status"] == "UNSOLD"
        assert len(winners) == (1 if bundle["status"] == "SOLD" else 0), \
            "winner cardinality conserved across the compensating pair"


class TestPaymentAndCompensationGates:

    def test_payment_exceeds_outstanding_rejected(self):
        """PRD section 3.7: "the amount must be at least one cent and at
        most the outstanding balance (`ERR_PAYMENT_EXCEEDS_BALANCE`
        otherwise) — partial payments are expressly allowed."

        Design: Corner/validations/payment_exceeds_outstanding_rejected
        """
        ctx = setup_sold_scenario(fmv_cents=40000, bid_amount=50000)
        invoice_id = ctx["invoice"]["id"]
        over = api_client.create_payment(
            invoice_id, {"amount_cents": 50001, "method": "CARD"},
            make_bidder_headers(ctx["bidder"]["id"]))
        validate_error(over, ApiErrorId.ERR_PAYMENT_EXCEEDS_BALANCE)

        exact = api_client.create_payment(
            invoice_id, {"amount_cents": 50000, "method": "CARD"},
            make_bidder_headers(ctx["bidder"]["id"]))
        payment = validate_success(exact, expected_status=201)
        assert payment["status"] == "INITIATED", "inclusive upper bound"

    def test_writeoff_partially_paid_forbidden(self):
        """PRD section 3.7: "it requires `payment_status` `UNPAID` (a
        `PARTIALLY_PAID` or `PAID` invoice is rejected with
        `ERR_WRITEOFF_FORBIDDEN`)"

        Design: Corner/validations/writeoff_partially_paid_forbidden
        """
        ctx = setup_sold_scenario(fmv_cents=40000, bid_amount=50000)
        invoice_id = ctx["invoice"]["id"]
        payment = _pay(invoice_id, 20000, ctx["bidder"]["id"])
        _settle(payment["id"])

        resp = api_client.write_off_invoice(invoice_id, FO)
        validate_error(resp, ApiErrorId.ERR_WRITEOFF_FORBIDDEN)

        invoice = get_success_data(api_client.get_invoice(invoice_id, FO))
        assert invoice["payment_status"] == "PARTIALLY_PAID"
        assert invoice["amount_paid_cents"] == 20000

    def test_refund_after_redemption_forbidden(self):
        """PRD section 3.7: "Refunding requires the invoice's
        `payment_status` to be `PAID` and any attached certificate to be
        in a status other than `REDEEMED` — redeemed experiences cannot be
        refunded — with both failures rejected as `ERR_REFUND_FORBIDDEN`."

        Design: Corner/validations/refund_after_redemption_forbidden
        """
        ctx = setup_paid_scenario(fmv_cents=40000, bid_amount=50000,
                                  kind="EXPERIENCE")
        cert = get_certificate_for_invoice(ctx["invoice"]["id"])
        validate_success(api_client.redeem_certificate(
            cert["id"],
            {"scheduled_start": "2027-01-10T00:00:00Z",
             "scheduled_end": "2027-01-12T00:00:00Z"},
            make_bidder_headers(ctx["bidder"]["id"]),
        ))

        resp = api_client.refund_invoice(ctx["invoice"]["id"], FO)
        validate_error(resp, ApiErrorId.ERR_REFUND_FORBIDDEN)

        invoice = get_success_data(
            api_client.get_invoice(ctx["invoice"]["id"], FO))
        assert invoice["payment_status"] == "PAID"

    def test_payment_on_paid_invoice_rejected(self):
        """PRD section 3.7: "the invoice's `payment_status` must be
        `UNPAID` or `PARTIALLY_PAID` (`ERR_INVOICE_NOT_PAYABLE`
        otherwise)"

        Design: Corner/validations/payment_on_paid_invoice_rejected
        """
        ctx = setup_paid_scenario(fmv_cents=40000, bid_amount=50000)
        resp = api_client.create_payment(
            ctx["invoice"]["id"], {"amount_cents": 1, "method": "CARD"},
            make_bidder_headers(ctx["bidder"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INVOICE_NOT_PAYABLE)

    def test_non_owner_cannot_pay_invoice(self):
        """PRD section 3.7: "Only the bidder who owns the invoice may pay
        it (`ERR_OWNERSHIP_VIOLATION` otherwise)" PRD section 2.1:
        "Ownership is enforced on exactly three operations:
        `POST /invoices/{id}/payments`,
        `POST /certificates/{id}/redeem`, and
        `POST /dispositions/{id}/donor-response`."

        Design: Corner/rbac/non_owner_cannot_pay_invoice
        """
        ctx = setup_sold_scenario(fmv_cents=40000, bid_amount=50000)
        other = create_bidder(ctx["event"]["id"], full_name="Bidder B")
        resp = api_client.create_payment(
            ctx["invoice"]["id"], {"amount_cents": 50000, "method": "CARD"},
            make_bidder_headers(other["id"]))
        validate_error(resp, ApiErrorId.ERR_OWNERSHIP_VIOLATION)

        own = api_client.create_payment(
            ctx["invoice"]["id"], {"amount_cents": 50000, "method": "CARD"},
            make_bidder_headers(ctx["bidder"]["id"]))
        payment = validate_success(own, expected_status=201)
        assert payment["status"] == "INITIATED"


class TestWriteOffCascadeAndFulfill:

    def test_writeoff_unpaid_invoice_cascade(self):
        """PRD section 3.7: "it runs the same unwind —
        `fulfillment_status` to `VOIDED`, a `PENDING_ISSUE` certificate to
        `VOIDED`, the `WINNER` bid to `VOID`, the bundle from `SOLD` to
        `UNSOLD`, member items from `SOLD` to `UNSOLD`, and one `PROPOSED`
        disposition per member item."

        Design: Corner/endpoints/writeoff_unpaid_invoice_cascade
        """
        ctx = setup_sold_scenario(fmv_cents=40000, bid_amount=50000)
        invoice = validate_success(
            api_client.write_off_invoice(ctx["invoice"]["id"], FO))
        assert_invoice(invoice)
        assert invoice["payment_status"] == "WRITTEN_OFF"
        assert invoice["fulfillment_status"] == "VOIDED"

        bids, _m = validate_paginated(
            api_client.list_bundle_bids(ctx["bundle"]["id"], ADMIN))
        assert bids[0]["status"] == "VOID"

        bundle = get_success_data(
            api_client.get_bundle(ctx["bundle"]["id"], ADMIN))
        assert bundle["status"] == "UNSOLD"

        item = get_success_data(
            api_client.get_item(ctx["items"][0]["id"], ADMIN))
        assert item["status"] == "UNSOLD"

        disposition = get_disposition_for_item(ctx["items"][0]["id"])
        assert disposition["status"] == "PROPOSED"

    def test_fulfill_physical_invoice_settles_bundle(self):
        """PRD section 3.8: "A `GalaAdmin` marks a physical-only invoice
        fulfilled, moving `fulfillment_status` from `READY` to
        `FULFILLED`; fulfillment requires `payment_status` `PAID`, and any
        attempt against a different payment state is rejected with
        `ERR_INVALID_STATE`. Here too the bundle bubbles from `SOLD` to
        `SETTLED`." PRD section 3.8: "The certificates of an invoice can
        be listed — the list holds zero or one element"

        Design: Corner/endpoints/fulfill_physical_invoice_settles_bundle
        """
        ctx = setup_paid_scenario(fmv_cents=40000, bid_amount=50000,
                                  kind="PHYSICAL")
        certs, _m = validate_paginated(
            api_client.list_invoice_certificates(ctx["invoice"]["id"],
                                                 ADMIN))
        assert len(certs) == 0, "physical-only invoice holds no certificate"

        invoice = validate_success(
            api_client.fulfill_invoice(ctx["invoice"]["id"], ADMIN))
        assert invoice["fulfillment_status"] == "FULFILLED"
        assert invoice["payment_status"] == "PAID"

        bundle = get_success_data(
            api_client.get_bundle(ctx["bundle"]["id"], ADMIN))
        assert bundle["status"] == "SETTLED", \
            "bubble-up on PAID + FULFILLED"
