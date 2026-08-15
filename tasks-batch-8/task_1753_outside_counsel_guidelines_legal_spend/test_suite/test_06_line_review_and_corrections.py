"""Manual line review, adjustment boundaries, and post-approval corrections (PRD §3.6)."""
from test_helpers import (
    ApiErrorId,
    clean_line,
    file_appeal,
    claim_appeal,
    get_invoice,
    get_line_by_task_code,
    get_line_item,
    get_matter,
    grant_appeal,
    list_line_items,
    ops_headers,
    rate_not_on_card_line,
    setup_billing_ready,
    submit_invoice,
    validate_error,
    validate_success,
)


class TestAdjustmentBoundaries:
    """adjusted_amount_cents: >= 0 is inclusive, < amount_cents is exclusive."""

    def _pending_line_setup(self, api):
        ctx = setup_billing_ready()
        dept_id, firm_id = ctx["dept"]["id"], ctx["firm"]["id"]
        invoice = submit_invoice(
            dept_id, ctx["matter"]["id"], firm_id, ctx["matter_version"],
            [rate_not_on_card_line(ctx["timekeeper"]["id"], "L110", 1.00, 90_000)],
            invoice_number="INV-ADJ",
        )
        line = list_line_items(dept_id, ctx["matter"]["id"], invoice["id"])[0]
        return ctx, invoice, line

    def test_adjust_to_zero_allowed(self, api, legal_ops_headers):
        """PRD §3.6: "It may be adjust-approved (`PENDING → ADJUSTED_APPROVED`) with a reviewer-supplied `adjusted_amount_cents`, which must be at least zero and strictly less than the line's `amount_cents` (`ERR_INVALID_ADJUSTMENT`)."
        PRD §3.5: "The invoice's `approved_total_cents` is recomputed on the same triggers: a line contributes its `adjusted_amount_cents` when `ADJUSTED_APPROVED`, its `amount_cents` when `APPROVED` or `REINSTATED`, and zero in any other status."

        Design: Difficulty/boundary_precision_check/adjustment_amount_zero_and_full_boundaries
        """
        ctx, invoice, line = self._pending_line_setup(api)
        dept_id = ctx["dept"]["id"]
        assert line["review_status"] == "PENDING", "rate-not-on-card must leave the line PENDING"
        assert line["amount_cents"] == 90_000

        adjusted = validate_success(
            api.adjust_line_item(dept_id, ctx["matter"]["id"], invoice["id"], line["id"],
                                 {"adjusted_amount_cents": 0}, legal_ops_headers)
        )
        assert adjusted["review_status"] == "ADJUSTED_APPROVED", (
            f"0 satisfies the inclusive lower bound, got {adjusted['review_status']}"
        )
        inv = get_invoice(dept_id, ctx["matter"]["id"], invoice["id"])
        assert inv["approved_total_cents"] == 0, (
            f"an ADJUSTED_APPROVED line contributes its adjusted amount (0), got {inv['approved_total_cents']}"
        )

    def test_adjust_to_full_amount_rejected(self, api, legal_ops_headers):
        """PRD §3.6: "It may be adjust-approved (`PENDING → ADJUSTED_APPROVED`) with a reviewer-supplied `adjusted_amount_cents`, which must be at least zero and strictly less than the line's `amount_cents` (`ERR_INVALID_ADJUSTMENT`)."

        Design: Difficulty/boundary_precision_check/adjustment_amount_zero_and_full_boundaries
        """
        ctx, invoice, line = self._pending_line_setup(api)
        dept_id = ctx["dept"]["id"]
        assert line["amount_cents"] == 90_000

        # 90000 == amount_cents violates the exclusive upper bound.
        resp = api.adjust_line_item(dept_id, ctx["matter"]["id"], invoice["id"], line["id"],
                                    {"adjusted_amount_cents": 90_000}, legal_ops_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_ADJUSTMENT)
        line_after = get_line_item(dept_id, ctx["matter"]["id"], invoice["id"], line["id"])
        assert line_after["review_status"] == "PENDING", (
            f"rejected adjustment must leave the line PENDING, got {line_after['review_status']}"
        )


class TestBilledToDateInvariant:
    """Reject-after-approval debits the matter; appeal grant credits it back exactly."""

    def _approved_two_line_invoice(self, api):
        ctx = setup_billing_ready()
        dept_id, firm_id = ctx["dept"]["id"], ctx["firm"]["id"]
        tk_id = ctx["timekeeper"]["id"]
        invoice = submit_invoice(
            dept_id, ctx["matter"]["id"], firm_id, ctx["matter_version"],
            [clean_line(tk_id, "L110", 10.00, 100_000), clean_line(tk_id, "L120", 5.00, 100_000)],
            invoice_number="INV-I",
        )
        lines = list_line_items(dept_id, ctx["matter"]["id"], invoice["id"])
        line2 = get_line_by_task_code(lines, "L120")
        return ctx, invoice, line2

    def test_manual_reject_after_approval_debits_matter(self, api, legal_ops_headers):
        """PRD §3.6: "While the parent invoice is `APPROVED` or `PARTIALLY_APPROVED`, a reviewer may still reject a line that is `APPROVED` or `ADJUSTED_APPROVED`; the rejection sets its `rejection_reason_code`, recomputes the invoice totals with the line excluded, and the matter's `billed_to_date_cents` decreases by the line's prior contribution — its `amount_cents` for a formerly approved line, or its `adjusted_amount_cents` for a formerly adjust-approved line."

        Design: Difficulty/compensating_invariant/billed_to_date_invariant_under_reject_reinstate
        """
        ctx, invoice, line2 = self._approved_two_line_invoice(api)
        dept_id = ctx["dept"]["id"]
        billed_initial = get_matter(dept_id, ctx["matter"]["id"])["billed_to_date_cents"]
        assert billed_initial == 1_500_000, f"both clean lines book 1500000, got {billed_initial}"

        rejected = validate_success(
            api.reject_line_item(dept_id, ctx["matter"]["id"], invoice["id"], line2["id"],
                                 {"rejection_reason_code": "OVER_BUDGET"}, legal_ops_headers)
        )
        assert rejected["review_status"] == "REJECTED"
        assert rejected["rejection_reason_code"] == "OVER_BUDGET"
        inv = get_invoice(dept_id, ctx["matter"]["id"], invoice["id"])
        assert inv["approved_total_cents"] == 1_000_000, (
            f"totals recompute with the line excluded, got {inv['approved_total_cents']}"
        )
        billed_after = get_matter(dept_id, ctx["matter"]["id"])["billed_to_date_cents"]
        assert billed_after == 1_000_000, (
            f"compensating debit of the line's 500000 contribution, got {billed_after}"
        )

    def test_appeal_grant_restores_billed_to_date_zero_drift(self, api, legal_ops_headers):
        """PRD §3.6: "While the parent invoice is `APPROVED` or `PARTIALLY_APPROVED`, a reviewer may still reject a line that is `APPROVED` or `ADJUSTED_APPROVED`; the rejection sets its `rejection_reason_code`, recomputes the invoice totals with the line excluded, and the matter's `billed_to_date_cents` decreases by the line's prior contribution — its `amount_cents` for a formerly approved line, or its `adjusted_amount_cents` for a formerly adjust-approved line."
        PRD §3.6: "Granting (`UNDER_REVIEW → GRANTED`) fires a three-hop cascade: the line transitions `REJECTED → REINSTATED` and its `rejection_reason_code` is cleared; the invoice's `approved_total_cents` is recomputed with the line's amount included again; and the matter's `billed_to_date_cents` increases by the line's `amount_cents` as a compensating credit on top of whatever was already booked."

        Design: Difficulty/compensating_invariant/billed_to_date_invariant_under_reject_reinstate
        """
        ctx, invoice, line2 = self._approved_two_line_invoice(api)
        dept_id, firm_id = ctx["dept"]["id"], ctx["firm"]["id"]
        billed_initial = get_matter(dept_id, ctx["matter"]["id"])["billed_to_date_cents"]
        assert billed_initial == 1_500_000

        validate_success(
            api.reject_line_item(dept_id, ctx["matter"]["id"], invoice["id"], line2["id"],
                                 {"rejection_reason_code": "OVER_BUDGET"}, legal_ops_headers)
        )
        assert get_matter(dept_id, ctx["matter"]["id"])["billed_to_date_cents"] == 1_000_000

        appeal = file_appeal(dept_id, ctx["matter"]["id"], invoice["id"], line2["id"], firm_id,
                             rationale="not over budget")
        claim_appeal(dept_id, ctx["matter"]["id"], invoice["id"], line2["id"], appeal["id"])
        grant_appeal(dept_id, ctx["matter"]["id"], invoice["id"], line2["id"], appeal["id"], note="restore")

        billed_final = get_matter(dept_id, ctx["matter"]["id"])["billed_to_date_cents"]
        assert billed_final == 1_500_000, (
            f"compensating credit must restore the exact debited amount, got {billed_final}"
        )
        assert billed_final - billed_initial == 0, (
            f"zero-drift invariant violated: initial {billed_initial}, final {billed_final}"
        )
