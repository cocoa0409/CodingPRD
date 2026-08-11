"""Payments, waterfall allocation, write-offs, reversals, and recovered-funds
conservation (PRD §3.5, §3.6)."""
from test_helpers import (
    ApiErrorId,
    assert_payment,
    create_excavator,
    get_case,
    get_excavator,
    get_invoice,
    make_excavator_headers,
    make_manager_headers,
    record_payment,
    set_clock,
    setup_disputed_invoice,
    setup_issued_invoice_case,
    setup_paid_case,
    validate_error,
    validate_success,
)

MANAGER = make_manager_headers("mgr-1")


class TestPaymentWaterfall:
    def test_payment_waterfall_oldest_due_first(self, api):
        """PRD §3.6: "the payment distributes via a waterfall across the payer's
        candidate invoices — those with `status` in `ISSUED` or `PARTIALLY_PAID` —
        ordered by `due_at` ascending with ties broken by `created_at` ascending. The
        walk fills each candidate to zero due before moving to the next"

        Design: Corner/calculations/payment_waterfall_oldest_due_first
        """
        excavator = create_excavator()
        # Invoice A: issued under the default clock (2026-05-01), due 2026-05-31.
        ctx_a = setup_issued_invoice_case(
            dig_site_address="16 Alpha St", severity="MINOR",
            occurred_at="2026-05-01T09:00:00Z", excavator=excavator,
        )
        inv_a = ctx_a["invoice"]
        assert inv_a["due_at"].startswith("2026-05-31"), (
            f"invoice A issued at the default clock falls due 2026-05-31, got {inv_a['due_at']}"
        )
        set_clock("2026-05-02T00:00:00Z")
        # Invoice B for the same payer, issued one clock-day later, due 2026-06-01.
        ctx_b = setup_issued_invoice_case(
            dig_site_address="17 Beta St", severity="MINOR",
            occurred_at="2026-05-01T11:00:00Z", excavator=excavator,
        )
        inv_b = ctx_b["invoice"]
        assert inv_b["due_at"].startswith("2026-06-01"), (
            f"invoice B issued 2026-05-02 falls due 2026-06-01, got {inv_b['due_at']}"
        )
        payment = record_payment("EXCAVATOR", excavator["id"], 150000)
        assert_payment(payment)
        assert payment["allocations"] == [
            {"claim_invoice_id": inv_a["id"], "amount_cents": 120000},
            {"claim_invoice_id": inv_b["id"], "amount_cents": 30000},
        ], f"waterfall must fill the earlier-due invoice first, got {payment['allocations']}"
        inv_a_after = get_invoice(inv_a["id"])
        inv_b_after = get_invoice(inv_b["id"])
        assert inv_a_after["status"] == "PAID"
        assert inv_b_after["status"] == "PARTIALLY_PAID"
        assert inv_b_after["amount_due_cents"] == 90000

    def test_explicit_payment_over_invoice_balance_rejected(self, api):
        """PRD §3.6: "When `claim_invoice_id` is supplied, the payment applies as a
        single leg of the full `amount_cents` against that invoice; the amount must not
        exceed the invoice's `amount_due_cents` (otherwise `ERR_PAYMENT_EXCEEDS_BALANCE`,
        HTTP 409)."

        Design: Corner/validations/explicit_payment_over_invoice_balance_rejected
        """
        ctx = setup_issued_invoice_case(dig_site_address="27 Mu St")
        excavator = ctx["excavator"]
        invoice = ctx["invoice"]
        assert invoice["amount_due_cents"] == 120000
        resp_over = api.create_payment(
            {
                "payer_type": "EXCAVATOR", "payer_id": excavator["id"],
                "amount_cents": 120001, "claim_invoice_id": invoice["id"],
            },
            make_excavator_headers(excavator["id"]),
        )
        validate_error(resp_over, ApiErrorId.ERR_PAYMENT_EXCEEDS_BALANCE, expected_status=409)
        payment = record_payment("EXCAVATOR", excavator["id"], 120000,
                                 claim_invoice_id=invoice["id"])
        assert_payment(payment)
        assert payment["status"] == "APPLIED"

    def test_immediate_consistency_payment_effects_visible(self, api):
        """PRD §3.6: "The computed legs are stored on the payment as an `allocations`
        array of `{ claim_invoice_id, amount_cents }` entries." and "when
        `amount_paid_cents` reaches `invoiced_cents` the invoice moves to `PAID`." The
        creation response already carries the legs and an immediate re-read shows the
        invoice settled.

        Design: Corner/consistency_model/immediate_consistency_payment_effects_visible
        """
        ctx = setup_issued_invoice_case(dig_site_address="48 Teth St")
        excavator = ctx["excavator"]
        invoice = ctx["invoice"]
        resp = api.create_payment(
            {
                "payer_type": "EXCAVATOR", "payer_id": excavator["id"],
                "amount_cents": 120000, "claim_invoice_id": invoice["id"],
            },
            make_excavator_headers(excavator["id"]),
        )
        payment = validate_success(resp, expected_status=201)
        assert payment["status"] == "APPLIED"
        assert payment["allocations"] == [
            {"claim_invoice_id": invoice["id"], "amount_cents": 120000}
        ]
        invoice_after = get_invoice(invoice["id"])
        assert invoice_after["amount_due_cents"] == 0
        assert invoice_after["status"] == "PAID"


class TestPaymentOwnership:
    def test_excavator_cannot_pay_for_other_returns_ownership(self, api):
        """PRD §3.6: "For the `Excavator` and `Locator` roles the caller's `X-User-ID`
        must equal `payer_id` (otherwise `ERR_OWNERSHIP_MISMATCH`)"

        Design: Corner/rbac/excavator_cannot_pay_for_other_returns_ownership
        """
        ex1 = create_excavator()
        ex2 = create_excavator(company_name="OtherCo", contact_email="o@x.com")
        resp = api.create_payment(
            {"payer_type": "EXCAVATOR", "payer_id": ex1["id"], "amount_cents": 1000},
            make_excavator_headers(ex2["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_OWNERSHIP_MISMATCH, expected_status=403)


class TestWriteOff:
    def test_writeoff_over_cap_rejected(self, api):
        """PRD §3.5: "the invoice's `amount_due_cents` is at most 20000 cents (two
        hundred dollars) (otherwise `ERR_WRITE_OFF_CAP_EXCEEDED`, HTTP 409)."

        Design: Corner/errors/writeoff_over_cap_rejected
        """
        ctx = setup_issued_invoice_case(dig_site_address="42 Gimel St")
        invoice = ctx["invoice"]
        assert invoice["amount_due_cents"] == 120000
        resp = api.write_off_claim_invoice(invoice["id"], headers=MANAGER)
        validate_error(resp, ApiErrorId.ERR_WRITE_OFF_CAP_EXCEEDED, expected_status=409)
        assert get_invoice(invoice["id"])["status"] == "ISSUED"

    def test_writeoff_blocked_by_open_dispute(self, api):
        """PRD §3.5: "no `Dispute` on that invoice is in `OPEN`, `UNDER_REVIEW`, or
        `COUNTERED` (otherwise `ERR_INVOICE_HAS_OPEN_DISPUTE`, HTTP 409)"

        Design: Corner/validations/writeoff_blocked_by_open_dispute
        """
        ctx = setup_disputed_invoice(dig_site_address="26 Lambda St")
        invoice = ctx["invoice"]
        resp = api.write_off_claim_invoice(invoice["id"], headers=MANAGER)
        validate_error(resp, ApiErrorId.ERR_INVOICE_HAS_OPEN_DISPUTE, expected_status=409)
        assert get_invoice(invoice["id"])["status"] == "DISPUTED"

    def test_writeoff_success_under_cap_conditional_action(self, api):
        """PRD §3.5: "A successful write-off moves the invoice to `WRITTEN_OFF`, forgives
        the remaining `amount_due_cents`, recomputes the debtor's
        `total_outstanding_cents`, and may advance the parent case to `RECOVERED` per
        §3.6." Paying 105000 of a 120000 invoice drops the due to 15000 <= 20000.

        Design: Corner/endpoints/writeoff_success_under_cap_conditional_action
        """
        ctx = setup_issued_invoice_case(dig_site_address="29 Xi St")
        excavator = ctx["excavator"]
        invoice = ctx["invoice"]
        record_payment("EXCAVATOR", excavator["id"], 105000, claim_invoice_id=invoice["id"])
        invoice_mid = get_invoice(invoice["id"])
        assert invoice_mid["amount_due_cents"] == 15000
        resp = api.write_off_claim_invoice(invoice["id"], headers=MANAGER)
        written = validate_success(resp)
        assert written["status"] == "WRITTEN_OFF"
        assert written["amount_due_cents"] == 0
        case_after = get_case(ctx["case"]["id"])
        assert case_after["recovery_status"] == "RECOVERED"


class TestPaymentReversal:
    def test_reversal_reopens_paid_invoice(self, api):
        """PRD §3.6: "Reversal moves the payment to `REVERSED`, undoes every allocation
        leg (each targeted invoice's `amount_paid_cents` is reduced and its status is
        recomputed from the resulting value: zero yields `ISSUED`, between zero and
        `invoiced_cents` yields `PARTIALLY_PAID`, equal to `invoiced_cents` yields
        `PAID`)"

        Design: Difficulty/transitive_cascade/payment_reversal_reopens_invoice_and_case
        """
        ctx = setup_paid_case(dig_site_address="20 Hill St")
        invoice = ctx["invoice"]
        case = ctx["case"]
        assert invoice["status"] == "PAID"
        assert case["recovery_status"] == "RECOVERED"
        assert case["total_recovered_cents"] == 120000
        resp = api.reverse_payment(ctx["payment"]["id"], headers=MANAGER)
        reversed_payment = validate_success(resp)
        assert reversed_payment["status"] == "REVERSED"
        invoice_after = get_invoice(invoice["id"])
        assert invoice_after["amount_paid_cents"] == 0
        assert invoice_after["status"] == "ISSUED"

    def test_reversal_demotes_case_recovered_to_collecting(self, api):
        """PRD §3.6: "recomputes the case's `recovery_status` — in particular, if a
        terminal invoice reopens, the case moves from `RECOVERED` back to `COLLECTING`."

        Design: Difficulty/transitive_cascade/payment_reversal_reopens_invoice_and_case
        """
        ctx = setup_paid_case(dig_site_address="20 Hill St")
        case = ctx["case"]
        assert case["recovery_status"] == "RECOVERED"
        validate_success(api.reverse_payment(ctx["payment"]["id"], headers=MANAGER))
        case_after = get_case(case["id"])
        assert case_after["recovery_status"] == "COLLECTING"
        assert case_after["total_recovered_cents"] == 0


class TestRecoveredFundsConservation:
    def _setup_waterfall_with_remainder(self):
        ctx = setup_issued_invoice_case(dig_site_address="80 Shore Dr")
        excavator = ctx["excavator"]
        invoice = ctx["invoice"]
        assert get_excavator(excavator["id"])["credit_balance_cents"] == 0
        payment = record_payment("EXCAVATOR", excavator["id"], 150000)
        return ctx, excavator, invoice, payment

    def test_waterfall_remainder_lands_in_credit_balance(self, api):
        """PRD §3.6: "Any remainder after all candidates are filled is added to the
        payer's `credit_balance_cents`." A 150000 waterfall against a single 120000
        invoice fills it and credits 30000.

        Design: Difficulty/compensating_invariant/payment_apply_reverse_conserves_recovered_funds
        """
        _ctx, excavator, invoice, payment = self._setup_waterfall_with_remainder()
        invoice_after = get_invoice(invoice["id"])
        assert invoice_after["amount_paid_cents"] == 120000
        assert invoice_after["status"] == "PAID"
        excavator_after = get_excavator(excavator["id"])
        assert excavator_after["credit_balance_cents"] == 30000

    def test_reversal_claws_back_credit_and_paid_amounts(self, api):
        """PRD §3.6: "reduces the payer's `credit_balance_cents` by any remainder leg
        this payment had created" — apply followed by the compensating reversal leaves
        zero drift in either `amount_paid_cents` or `credit_balance_cents`.

        Design: Difficulty/compensating_invariant/payment_apply_reverse_conserves_recovered_funds
        """
        _ctx, excavator, invoice, payment = self._setup_waterfall_with_remainder()
        validate_success(api.reverse_payment(payment["id"], headers=MANAGER))
        invoice_after = get_invoice(invoice["id"])
        excavator_after = get_excavator(excavator["id"])
        assert invoice_after["amount_paid_cents"] == 0
        assert excavator_after["credit_balance_cents"] == 0, (
            "apply + compensate must conserve recovered funds with zero drift"
        )
