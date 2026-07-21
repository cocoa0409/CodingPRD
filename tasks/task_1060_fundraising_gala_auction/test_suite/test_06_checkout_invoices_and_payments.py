"""Invoice totals, the payment cascade and its compensating void."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_receipt,
    capture_payment,
    invoice_lines_of_type,
    make_finance_headers,
    read_auction_item,
    read_event,
    read_invoice,
    read_payment,
    setup_awarded_lot_scenario,
    setup_finalized_invoice_scenario,
    setup_paid_invoice_scenario,
    validate_error,
    validate_success,
    void_payment,
)


class TestProcessingFeeTier:
    """PRD §3.7's fee tier, resolved once from the pre-fee subtotal."""

    def _setup(self):
        return setup_awarded_lot_scenario(
            bid_amount_cents=49_900,
            invoice_overrides={"cover_processing_fee": True},
            starting_bid_cents=49_900,
            title="Signed Cello",
        )

    def test_processing_fee_uses_tier_selected_from_prefee_subtotal(self, api):
        """PRD §3.7: "Second, the fee tier is selected from that pre-fee
        subtotal: a subtotal strictly below 50,000 cents takes the 2.9 percent
        rate; a subtotal at or above 50,000 cents but strictly below 500,000
        cents takes the 2.4 percent rate; a subtotal at or above 500,000 cents
        takes the 1.9 percent rate."
        PRD §3.7: "Third, `processing_fee_cents` is the subtotal multiplied by
        the selected rate, rounded half up to a whole cent, plus a flat 30 cents
        — the rounding is applied once, to the percentage component only, before
        the flat component is added."

        Design: Difficulty/combinatorial_formula/invoice_processing_fee_tier_pinned_to_prefee_subtotal
        """
        env = self._setup()

        assert env["lot"]["hammer_price_cents"] == 49_900
        invoice = read_invoice(env["invoice_id"])
        assert invoice["line_subtotal_cents"] == 49_900, (
            f"The pre-fee subtotal is the hammer price, got "
            f"{invoice['line_subtotal_cents']}"
        )
        assert invoice["processing_fee_cents"] == 1_477, (
            "49900 at 2.9 percent rounds to 1447, plus the flat 30, is 1477; got "
            f"{invoice['processing_fee_cents']}"
        )

    def test_grossed_up_total_does_not_re_derive_the_fee_tier(self, api):
        """PRD §3.7: "The tier and fee are resolved once from the pre-fee
        subtotal and are never re-derived against the grossed-up total, even
        when adding the fee would have crossed a tier boundary."
        PRD §3.7: "Fourth, the fee becomes a real charge only when the guest
        elected to cover it: when `cover_processing_fee` is true,
        `total_due_cents` is `line_subtotal_cents` plus `processing_fee_cents`
        and a `PROCESSING_FEE` line for that amount is present among
        `line_items`; when it is false, `total_due_cents` is simply
        `line_subtotal_cents`."

        Design: Difficulty/combinatorial_formula/invoice_processing_fee_tier_pinned_to_prefee_subtotal
        """
        env = self._setup()

        invoice = read_invoice(env["invoice_id"])
        assert invoice["total_due_cents"] == 51_377, (
            f"49900 plus the 1477 fee is 51377, got {invoice['total_due_cents']}"
        )
        assert invoice["total_due_cents"] > 50_000, (
            "The grossed-up total crosses the tier-1 ceiling"
        )
        assert invoice["processing_fee_cents"] == 1_477, (
            "yet the fee stays at the tier-1 figure rather than being re-derived"
        )
        fee_lines = invoice_lines_of_type(invoice, "PROCESSING_FEE")
        assert len(fee_lines) == 1, (
            f"A covered fee appears as its own line, got {len(fee_lines)}"
        )
        assert fee_lines[0]["amount_cents"] == 1_477
        assert invoice["balance_due_cents"] == 51_377


class TestPaymentCaptureCascade:
    """PRD §3.7's capture cascade, from invoice through lot to event rollups."""

    def test_payment_capture_drives_invoice_to_paid_and_settles_the_lot(self, api):
        """PRD §3.7: "If the capture clears the balance to exactly zero, the
        invoice moves to `PAID` — from `PENDING_PAYMENT` directly if this was
        the only payment, or from `PARTIALLY_PAID` if earlier payments had
        already landed — and the same full cascade runs in both cases: every
        auction lot whose `invoice_id` is this invoice moves its
        `settlement_status` `INVOICED → PAID`, every paddle-raise gift likewise,
        and every ticket order moves its `payment_status` `INVOICED → PAID`; the
        event then recomputes `gross_collected_cents` and `unpaid_invoice_count`
        and re-derives its posture; the guest recomputes
        `outstanding_balance_cents`; and the invoice's `version` advances."
        PRD §3.7: "The transaction is stored in `CAPTURED` status with
        `captured_by_user_id` set to the acting `X-User-ID`, and with
        `voided_by_user_id` and `void_reason` both null."

        Design: Difficulty/transitive_cascade/payment_capture_cascades_to_event_rollups
        """
        env = setup_finalized_invoice_scenario()

        response = api.create_payment(
            {"invoice_id": env["invoice_id"], "amount_cents": 12_500, "method": "CARD"},
            TEST_USERS["finance_headers"],
        )
        payment = validate_success(response, 201)

        assert payment["status"] == "CAPTURED"
        assert payment["captured_by_user_id"] == "fin-1", (
            f"captured_by_user_id records the acting operator, got "
            f"{payment['captured_by_user_id']}"
        )
        assert payment["voided_by_user_id"] is None
        assert payment["void_reason"] is None
        assert read_invoice(env["invoice_id"])["status"] == "PAID"
        assert read_auction_item(env["lot"]["id"])["settlement_status"] == "PAID"

    def test_payment_capture_recomputes_event_gross_and_unpaid_counts(self, api):
        """PRD §3.7: "An event's `gross_collected_cents` is at all times the sum
        of `amount_cents` over `CAPTURED` payment transactions across all of
        that event's invoices, and its `unpaid_invoice_count` is the number of
        its invoices in `PENDING_PAYMENT` or `PARTIALLY_PAID`."

        Design: Difficulty/transitive_cascade/payment_capture_cascades_to_event_rollups
        """
        env = setup_finalized_invoice_scenario()
        before = read_event(env["event"]["id"])
        assert before["gross_collected_cents"] == 0
        assert before["unpaid_invoice_count"] == 1, (
            "A finalized, unpaid invoice counts as unpaid"
        )

        capture_payment(env["invoice_id"], 12_500)

        after = read_event(env["event"]["id"])
        assert after["gross_collected_cents"] == 12_500, (
            f"The captured cash lands on the event rollup, got "
            f"{after['gross_collected_cents']}"
        )
        assert after["unpaid_invoice_count"] == 0, (
            f"The paid invoice leaves the unpaid tally, got "
            f"{after['unpaid_invoice_count']}"
        )


class TestPaymentVoidCompensates:
    """PRD §3.7's void, which must unwind exactly what the capture did."""

    def test_payment_void_returns_invoice_to_pending_payment(self, api):
        """PRD §3.7: "A void against a `PAID` invoice that leaves
        `amount_paid_cents` at exactly zero moves it `PAID → PENDING_PAYMENT`,
        runs the identical settlement unwind, has the event recompute
        `gross_collected_cents` — which decreases by the voided amount — and
        `unpaid_invoice_count`, has the guest recompute
        `outstanding_balance_cents`, and advances the invoice's `version`."
        PRD §3.7: "The caller supplies a `reason`, which is stored as the
        transaction's `void_reason` alongside `voided_by_user_id`; the
        transaction moves `CAPTURED → VOIDED` and its `version` advances."

        Design: Difficulty/compensating_invariant/payment_void_restores_event_gross_collected_to_zero
        """
        env = setup_paid_invoice_scenario()

        response = api.void_payment(
            env["payment"]["id"],
            "Card chargeback received from processor.",
            make_finance_headers("fin-2"),
        )
        payment = validate_success(response, 200)

        assert payment["status"] == "VOIDED"
        assert payment["voided_by_user_id"] == "fin-2", (
            f"voided_by_user_id records the voiding operator, got "
            f"{payment['voided_by_user_id']}"
        )
        invoice = read_invoice(env["invoice_id"])
        assert invoice["status"] == "PENDING_PAYMENT", (
            f"A fully unwound invoice returns to PENDING_PAYMENT, got "
            f"{invoice['status']}"
        )
        assert invoice["amount_paid_cents"] == 0
        assert invoice["balance_due_cents"] == 12_500
        assert read_auction_item(env["lot"]["id"])["settlement_status"] == "INVOICED", (
            "The settlement unwind returns the lot to INVOICED"
        )

    def test_payment_void_restores_event_gross_collected_to_zero(self, api):
        """PRD §3.7: "An event's `gross_collected_cents` is at all times the sum
        of `amount_cents` over `CAPTURED` payment transactions across all of
        that event's invoices, and its `unpaid_invoice_count` is the number of
        its invoices in `PENDING_PAYMENT` or `PARTIALLY_PAID`."
        PRD §3.7: "Fifth, `amount_paid_cents` is the sum of `amount_cents`
        across the invoice's payment transactions in `CAPTURED` status, with
        `VOIDED` transactions excluded, and `balance_due_cents` is
        `total_due_cents` less `amount_paid_cents`."

        Design: Difficulty/compensating_invariant/payment_void_restores_event_gross_collected_to_zero
        """
        env = setup_paid_invoice_scenario()
        assert read_event(env["event"]["id"])["gross_collected_cents"] == 12_500

        void_payment(env["payment"]["id"], user_id="fin-2")

        event = read_event(env["event"]["id"])
        assert event["gross_collected_cents"] == 0, (
            f"The compensating void leaves no money drift, got "
            f"{event['gross_collected_cents']}"
        )
        assert event["unpaid_invoice_count"] == 1, (
            "The invoice is unpaid once more"
        )
        assert read_payment(env["payment"]["id"])["status"] == "VOIDED"


def test_payment_above_balance_is_refused(api):
    """PRD §3.7: "The invoice must be in a payable state — `PENDING_PAYMENT` or
    `PARTIALLY_PAID` — else `ERR_INVOICE_NOT_PAYABLE`, and the tendered amount
    may not exceed the invoice's `balance_due_cents`, else
    `ERR_PAYMENT_EXCEEDS_BALANCE` (HTTP 422)."

    Design: Corner/validations/payment_above_outstanding_balance_is_refused
    """
    env = setup_finalized_invoice_scenario()
    assert env["invoice"]["balance_due_cents"] == 12_500

    response = api.create_payment(
        {"invoice_id": env["invoice_id"], "amount_cents": 12_501, "method": "CARD"},
        TEST_USERS["finance_headers"],
    )

    validate_error(response, ApiErrorId.ERR_PAYMENT_EXCEEDS_BALANCE.value, 422)
    invoice = read_invoice(env["invoice_id"])
    assert invoice["amount_paid_cents"] == 0, "A refused capture takes no money"
    assert invoice["status"] == "PENDING_PAYMENT"


def test_capturer_cannot_void_their_own_payment(api):
    """PRD §2.9: "The operator who captured a payment — recorded as
    `captured_by_user_id` — may not be the operator who voids it. Either
    violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Design: Corner/rbac/payment_capturer_cannot_void_their_own_payment
    """
    env = setup_paid_invoice_scenario(captured_by="fin-1")

    response = api.void_payment(
        env["payment"]["id"], "Mistaken capture.", make_finance_headers("fin-1")
    )

    validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)
    assert read_payment(env["payment"]["id"])["status"] == "CAPTURED", (
        "A refused void leaves the payment CAPTURED"
    )
    assert read_event(env["event"]["id"])["gross_collected_cents"] == 12_500


def test_receipt_deducts_fair_market_value_from_hammer_price(api):
    """PRD §3.8: "For an `AUCTION_ITEM` line, the donor received goods, so the
    referenced lot's `estimated_fmv_cents` is added to the benefit total and the
    line's `amount_cents` less that same fair market value — floored at zero,
    never negative — is added to the deductible."
    PRD §3.8: "The receipt copies the invoice's `bidder_id`, stamps
    `issued_at_utc` from the logical clock, and records `total_paid_cents` as
    the invoice's `amount_paid_cents` at issue time — which, since the invoice
    is `PAID`, equals its `total_due_cents`."

    Design: Corner/calculations/receipt_deducts_fair_market_value_from_hammer_price
    """
    env = setup_paid_invoice_scenario()

    response = api.create_receipt(env["invoice_id"], TEST_USERS["finance_headers"])
    receipt = validate_success(response, 201)

    assert_receipt(receipt)
    assert receipt["total_paid_cents"] == 12_500
    assert receipt["benefit_value_cents"] == 4_000, (
        f"The lot's fair market value is the benefit, got "
        f"{receipt['benefit_value_cents']}"
    )
    assert receipt["tax_deductible_cents"] == 8_500, (
        f"12500 less the 4000 fair market value is 8500, got "
        f"{receipt['tax_deductible_cents']}"
    )
    assert receipt["bidder_id"] == env["bidders"][0]["id"]
    assert receipt["issued_at_utc"] == "2026-07-05T00:00:00.000Z", (
        f"issued_at_utc is stamped from the logical clock, got "
        f"{receipt['issued_at_utc']}"
    )
