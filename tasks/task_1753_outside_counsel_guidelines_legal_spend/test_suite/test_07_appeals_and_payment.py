"""Appeal cascades, payment freeze semantics, and terminal-state guards (PRD §3.6)."""
from test_helpers import (
    ApiErrorId,
    assert_appeal,
    block_billed_line,
    clean_line,
    claim_appeal,
    file_appeal,
    firm_headers,
    get_invoice,
    get_line_by_task_code,
    get_line_item,
    get_matter,
    grant_appeal,
    list_line_items,
    ops_headers,
    setup_billing_ready,
    setup_partially_approved_invoice,
    setup_rejected_invoice_with_claimed_appeal,
    submit_invoice,
    validate_error,
    validate_success,
)


class TestAppealGrantThreeHopCascade:
    """Appeal grant: line REINSTATED -> invoice totals recomputed -> matter credited."""

    def test_appeal_grant_reinstates_line_and_recomputes_invoice(self, api, legal_ops_headers):
        """PRD §3.6: "Granting (`UNDER_REVIEW → GRANTED`) fires a three-hop cascade: the line transitions `REJECTED → REINSTATED` and its `rejection_reason_code` is cleared; the invoice's `approved_total_cents` is recomputed with the line's amount included again; and the matter's `billed_to_date_cents` increases by the line's `amount_cents` as a compensating credit on top of whatever was already booked."

        Design: Difficulty/transitive_cascade/appeal_grant_three_hop_cascade
        """
        ctx = setup_partially_approved_invoice()
        dept_id, firm_id = ctx["dept"]["id"], ctx["firm"]["id"]
        matter_id, invoice_id = ctx["matter"]["id"], ctx["invoice"]["id"]
        line2 = ctx["line2"]
        assert line2["review_status"] == "REJECTED"
        assert line2["rejection_reason_code"] == "BLOCK_BILLING"

        appeal = file_appeal(dept_id, matter_id, invoice_id, line2["id"], firm_id,
                             rationale="Tasks were distinct")
        claim_appeal(dept_id, matter_id, invoice_id, line2["id"], appeal["id"])
        granted = grant_appeal(dept_id, matter_id, invoice_id, line2["id"], appeal["id"], note="accepted")
        assert_appeal(granted)
        assert granted["status"] == "GRANTED"

        line_after = get_line_item(dept_id, matter_id, invoice_id, line2["id"])
        assert line_after["review_status"] == "REINSTATED", (
            f"hop 1 must reinstate the line, got {line_after['review_status']}"
        )
        assert line_after["rejection_reason_code"] is None, (
            f"reinstatement clears the reason code, got {line_after['rejection_reason_code']!r}"
        )
        inv = get_invoice(dept_id, matter_id, invoice_id)
        assert inv["approved_total_cents"] == 200_000, (
            f"hop 2 recomputes totals with the line included again, got {inv['approved_total_cents']}"
        )

    def test_appeal_grant_credits_matter_and_promotes_invoice(self, api, legal_ops_headers):
        """PRD §3.6: "Granting (`UNDER_REVIEW → GRANTED`) fires a three-hop cascade: the line transitions `REJECTED → REINSTATED` and its `rejection_reason_code` is cleared; the invoice's `approved_total_cents` is recomputed with the line's amount included again; and the matter's `billed_to_date_cents` increases by the line's `amount_cents` as a compensating credit on top of whatever was already booked."
        PRD §3.5: "The invoice's aggregate status derives from its lines and is re-evaluated after every line-item review action and every appeal resolution: while any line remains `PENDING` the invoice stays `UNDER_REVIEW`; when every line sits in `APPROVED`, `ADJUSTED_APPROVED`, or `REINSTATED`, the invoice becomes `APPROVED`; when every line sits in `REJECTED` or `UPHELD`, it becomes `REJECTED`; anything in between yields `PARTIALLY_APPROVED`."

        Design: Difficulty/transitive_cascade/appeal_grant_three_hop_cascade
        """
        ctx = setup_partially_approved_invoice()
        dept_id, firm_id = ctx["dept"]["id"], ctx["firm"]["id"]
        matter_id, invoice_id = ctx["matter"]["id"], ctx["invoice"]["id"]
        assert get_matter(dept_id, matter_id)["billed_to_date_cents"] == 100_000

        appeal = file_appeal(dept_id, matter_id, invoice_id, ctx["line2"]["id"], firm_id,
                             rationale="Tasks were distinct")
        claim_appeal(dept_id, matter_id, invoice_id, ctx["line2"]["id"], appeal["id"])
        grant_appeal(dept_id, matter_id, invoice_id, ctx["line2"]["id"], appeal["id"], note="accepted")

        matter = get_matter(dept_id, matter_id)
        assert matter["billed_to_date_cents"] == 200_000, (
            f"hop 3 credits the matter by the reinstated 100000, got {matter['billed_to_date_cents']}"
        )
        inv = get_invoice(dept_id, matter_id, invoice_id)
        assert inv["status"] == "APPROVED", (
            f"with no line left REJECTED/UPHELD the invoice promotes to APPROVED, got {inv['status']}"
        )


class TestProvisionalVsFinalPayable:
    """approved_total_cents is provisional until PAID; final_payable_cents freezes at PAID."""

    def _invoice_with_pending_appeal(self, api):
        """Two clean lines (10h and 5h at 100000) auto-approved; line2 manually
        rejected; appeal filed and claimed. Invoice PARTIALLY_APPROVED with a
        pending appeal."""
        ctx = setup_billing_ready()
        dept_id, firm_id = ctx["dept"]["id"], ctx["firm"]["id"]
        tk_id = ctx["timekeeper"]["id"]
        invoice = submit_invoice(
            dept_id, ctx["matter"]["id"], firm_id, ctx["matter_version"],
            [clean_line(tk_id, "L110", 10.00, 100_000), clean_line(tk_id, "L120", 5.00, 100_000)],
            invoice_number="INV-001",
        )
        lines = list_line_items(dept_id, ctx["matter"]["id"], invoice["id"])
        line2 = get_line_by_task_code(lines, "L120")
        validate_success(
            api.reject_line_item(dept_id, ctx["matter"]["id"], invoice["id"], line2["id"],
                                 {"rejection_reason_code": "RATE_EXCEEDS_APPROVED"}, ops_headers())
        )
        appeal = file_appeal(dept_id, ctx["matter"]["id"], invoice["id"], line2["id"], firm_id,
                             rationale="Rate matches approved card")
        claim_appeal(dept_id, ctx["matter"]["id"], invoice["id"], line2["id"], appeal["id"])
        return ctx, invoice, line2, appeal

    def test_provisional_then_final_payable_after_appeal_grant(self, api, legal_ops_headers):
        """PRD §3.6: "Until payment, `final_payable_cents` simply tracks `approved_total_cents`; afterwards it is never recomputed, so two reads of the same invoice — one taken while an appeal was pending, one after payment — can legitimately show different payable figures for identical line data."
        PRD §3.6: "Payment transitions the invoice to `PAID`, increments its `version`, and freezes `final_payable_cents` to the then-current `approved_total_cents`."

        Design: Difficulty/dual_variant_calc/invoice_provisional_vs_final_payable
        """
        ctx, invoice, line2, appeal = self._invoice_with_pending_appeal(api)
        dept_id, matter_id = ctx["dept"]["id"], ctx["matter"]["id"]

        pre_grant = get_invoice(dept_id, matter_id, invoice["id"])
        assert pre_grant["status"] == "PARTIALLY_APPROVED"
        assert pre_grant["approved_total_cents"] == 1_000_000, (
            f"provisional total while the appeal is pending covers only line1, got {pre_grant['approved_total_cents']}"
        )
        assert pre_grant["final_payable_cents"] == 1_000_000, (
            f"pre-payment final_payable_cents tracks approved_total_cents, got {pre_grant['final_payable_cents']}"
        )

        grant_appeal(dept_id, matter_id, invoice["id"], line2["id"], appeal["id"], note="Rate verified")
        post_grant = get_invoice(dept_id, matter_id, invoice["id"])
        assert post_grant["approved_total_cents"] == 1_500_000, (
            f"the reinstated line rejoins the total, got {post_grant['approved_total_cents']}"
        )

        validate_success(api.pay_invoice(dept_id, matter_id, invoice["id"], legal_ops_headers))
        paid = get_invoice(dept_id, matter_id, invoice["id"])
        assert paid["status"] == "PAID"
        assert paid["final_payable_cents"] == 1_500_000, (
            f"final_payable_cents freezes the post-appeal total, got {paid['final_payable_cents']}"
        )

    def test_final_payable_tracks_approved_until_payment(self, api, legal_ops_headers):
        """PRD §3.6: "Until payment, `final_payable_cents` simply tracks `approved_total_cents`; afterwards it is never recomputed, so two reads of the same invoice — one taken while an appeal was pending, one after payment — can legitimately show different payable figures for identical line data."
        PRD §3.6: "Payment transitions the invoice to `PAID`, increments its `version`, and freezes `final_payable_cents` to the then-current `approved_total_cents`."

        Design: Difficulty/dual_variant_calc/invoice_provisional_vs_final_payable
        """
        ctx = setup_billing_ready()
        dept_id, firm_id = ctx["dept"]["id"], ctx["firm"]["id"]
        invoice = submit_invoice(
            dept_id, ctx["matter"]["id"], firm_id, ctx["matter_version"],
            [clean_line(ctx["timekeeper"]["id"], "L110", 1.00, 100_000)],
            invoice_number="INV-TRK",
        )
        pre_pay = get_invoice(dept_id, ctx["matter"]["id"], invoice["id"])
        assert pre_pay["status"] == "APPROVED"
        assert pre_pay["final_payable_cents"] == pre_pay["approved_total_cents"] == 100_000

        validate_success(api.pay_invoice(dept_id, ctx["matter"]["id"], invoice["id"], legal_ops_headers))
        post_pay = get_invoice(dept_id, ctx["matter"]["id"], invoice["id"])
        assert post_pay["status"] == "PAID"
        assert post_pay["final_payable_cents"] == 100_000, (
            f"the frozen final equals the approved total at payment time, got {post_pay['final_payable_cents']}"
        )
        assert post_pay["version"] == pre_pay["version"] + 1, "payment increments the invoice version"


def test_error_open_appeals_blocks_pay(api, legal_ops_headers):
    """PRD §3.6: "A `LegalOpsReviewer` may pay an `APPROVED` invoice at any time; a `PARTIALLY_APPROVED` invoice may be paid only once no appeal on any of its lines remains in `SUBMITTED` or `UNDER_REVIEW` (`ERR_OPEN_APPEALS`)."

    Design: Corner/errors/error_open_appeals_blocks_pay
    """
    ctx = setup_partially_approved_invoice()
    dept_id, firm_id = ctx["dept"]["id"], ctx["firm"]["id"]
    matter_id, invoice_id = ctx["matter"]["id"], ctx["invoice"]["id"]
    appeal = file_appeal(dept_id, matter_id, invoice_id, ctx["line2"]["id"], firm_id, rationale="appeal")
    claim_appeal(dept_id, matter_id, invoice_id, ctx["line2"]["id"], appeal["id"])

    resp = api.pay_invoice(dept_id, matter_id, invoice_id, legal_ops_headers)
    validate_error(resp, ApiErrorId.ERR_OPEN_APPEALS)
    inv = get_invoice(dept_id, matter_id, invoice_id)
    assert inv["status"] == "PARTIALLY_APPROVED", (
        f"blocked payment must leave the invoice PARTIALLY_APPROVED, got {inv['status']}"
    )


def test_pay_invoice_twice_returns_invalid_state(api, legal_ops_headers):
    """PRD §3.6: "Payment transitions the invoice to `PAID`, increments its `version`, and freezes `final_payable_cents` to the then-current `approved_total_cents`."
    PRD §3.6: "`PAID` and `VOID` are terminal."
    PRD §2.9: "4. State legality: the target resource is in a state from which the requested transition is permitted — otherwise `ERR_INVALID_STATE`."

    Design: Corner/state_machines/pay_invoice_twice_returns_invalid_state
    """
    ctx = setup_billing_ready()
    dept_id, firm_id = ctx["dept"]["id"], ctx["firm"]["id"]
    invoice = submit_invoice(
        dept_id, ctx["matter"]["id"], firm_id, ctx["matter_version"],
        [clean_line(ctx["timekeeper"]["id"], "L110", 1.00, 100_000)],
        invoice_number="INV-PP",
    )
    validate_success(api.pay_invoice(dept_id, ctx["matter"]["id"], invoice["id"], legal_ops_headers))

    resp = api.pay_invoice(dept_id, ctx["matter"]["id"], invoice["id"], legal_ops_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_paid_invoice_cannot_be_voided(api):
    """PRD §3.6: "A fully `REJECTED` invoice may instead be voided by the firm (`REJECTED → VOID`) — the acting user's firm must match the invoice's `panel_firm_id` (`ERR_FIRM_MISMATCH`) — which increments the invoice's `version` and closes the matter of record. `PAID` and `VOID` are terminal."
    PRD §2.9: "4. State legality: the target resource is in a state from which the requested transition is permitted — otherwise `ERR_INVALID_STATE`."

    Design: Corner/state_machines/paid_invoice_cannot_be_voided_terminal_lockdown
    """
    ctx = setup_billing_ready()
    dept_id, firm_id = ctx["dept"]["id"], ctx["firm"]["id"]
    invoice = submit_invoice(
        dept_id, ctx["matter"]["id"], firm_id, ctx["matter_version"],
        [clean_line(ctx["timekeeper"]["id"], "L110", 1.00, 100_000)],
        invoice_number="INV-T",
    )
    validate_success(api.pay_invoice(dept_id, ctx["matter"]["id"], invoice["id"], ops_headers()))

    resp = api.void_invoice(dept_id, ctx["matter"]["id"], invoice["id"], firm_headers(firm_id))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestStateBeatsFiscalOnPay:
    """Paying a VOID invoice: state legality (priority 4) is the surfaced error."""

    def _void_invoice_with_open_appeal(self, api):
        ctx = setup_billing_ready()
        dept_id, firm_id = ctx["dept"]["id"], ctx["firm"]["id"]
        tk_id = ctx["timekeeper"]["id"]
        invoice = submit_invoice(
            dept_id, ctx["matter"]["id"], firm_id, ctx["matter_version"],
            [block_billed_line(tk_id, "L110", 5.00, 100_000)],
            invoice_number="INV-P",
        )
        line = list_line_items(dept_id, ctx["matter"]["id"], invoice["id"])[0]
        assert line["review_status"] == "REJECTED"
        inv = get_invoice(dept_id, ctx["matter"]["id"], invoice["id"])
        assert inv["status"] == "REJECTED"
        # Appeal stays SUBMITTED (open) while the firm voids the REJECTED invoice.
        appeal = file_appeal(dept_id, ctx["matter"]["id"], invoice["id"], line["id"], firm_id,
                             rationale="appeal on rejected invoice")
        validate_success(api.void_invoice(dept_id, ctx["matter"]["id"], invoice["id"], firm_headers(firm_id)))
        return ctx, invoice, line, appeal

    def test_pay_void_invoice_with_open_appeal_returns_invalid_state(self, api, legal_ops_headers):
        """PRD §3.6: "A `LegalOpsReviewer` may pay an `APPROVED` invoice at any time; a `PARTIALLY_APPROVED` invoice may be paid only once no appeal on any of its lines remains in `SUBMITTED` or `UNDER_REVIEW` (`ERR_OPEN_APPEALS`)."
        PRD §2.9: "4. State legality: the target resource is in a state from which the requested transition is permitted — otherwise `ERR_INVALID_STATE`."
        PRD §3.6: "`PAID` and `VOID` are terminal."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_pay
        """
        ctx, invoice, line, appeal = self._void_invoice_with_open_appeal(api)
        dept_id = ctx["dept"]["id"]
        resp = api.pay_invoice(dept_id, ctx["matter"]["id"], invoice["id"], legal_ops_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_failed_pay_leaves_invoice_and_appeal_unchanged(self, api, legal_ops_headers):
        """PRD §3.6: "`PAID` and `VOID` are terminal."
        PRD §2.9: "When several checks could reject the same request, the server applies them in a fixed priority order so that the surfaced error is deterministic:"

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_pay
        """
        ctx, invoice, line, appeal = self._void_invoice_with_open_appeal(api)
        dept_id = ctx["dept"]["id"]
        validate_error(
            api.pay_invoice(dept_id, ctx["matter"]["id"], invoice["id"], legal_ops_headers),
            ApiErrorId.ERR_INVALID_STATE,
        )
        inv = get_invoice(dept_id, ctx["matter"]["id"], invoice["id"])
        assert inv["status"] == "VOID", f"rejected payment must not mutate state, got {inv['status']}"
        ap = validate_success(
            api.get_appeal(dept_id, ctx["matter"]["id"], invoice["id"], line["id"], appeal["id"], ops_headers())
        )
        assert ap["status"] == "SUBMITTED", (
            f"the open appeal must be untouched by the rejected payment, got {ap['status']}"
        )
