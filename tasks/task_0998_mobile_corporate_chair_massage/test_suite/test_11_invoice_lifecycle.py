"""Invoice lifecycle: credit-limit guard, live-invoice uniqueness, the
dispute/resolve cycle, and the outstanding-balance invariant."""
from test_helpers import (
    create_invoice,
    get_account,
    get_booking,
    get_invoice,
    setup_completed_booking_with_invoice,
    setup_issued_invoice,
    validate_error,
    validate_success,
)


class TestCreditLimitGuard:
    def test_credit_limit_blocks_invoice_issue(self, api):
        """PRD §3.8: "Two guards apply, the credit check first: issuance may
        not push the account's outstanding balance above its
        `credit_limit_cents` — the post-issue outstanding, meaning the
        current `outstanding_balance_cents` plus this invoice's
        `total_cents`, must stay within the limit, otherwise
        `ERR_CREDIT_LIMIT_EXCEEDED` — and no other live invoice may exist for
        the booking."

        Design: Corner/validations/credit_limit_blocks_invoice_issue
        """
        ctx = setup_completed_booking_with_invoice(
            num_claims_completed=3,
            account_overrides={"credit_limit_cents": 5000},
        )
        invoice = ctx["invoice"]
        assert invoice["total_cents"] > 5000, (
            "Setup: invoice total must exceed the 5000-cent credit limit"
        )
        resp = api.issue_invoice(invoice["id"], ctx["admin"])
        validate_error(resp, "ERR_CREDIT_LIMIT_EXCEEDED", expected_status=422)
        assert get_invoice(ctx, invoice["id"])["status"] == "DRAFT"
        assert get_booking(ctx, ctx["booking"]["id"])["billing_status"] == "UNBILLED"
        assert get_account(ctx)["outstanding_balance_cents"] == 0


class TestLiveInvoiceUniqueness:
    def test_live_invoice_uniqueness_blocks_second_draft(self, api):
        """PRD §3.8: "Billing is invoice-driven, and exactly one live invoice
        — one in `DRAFT`, `ISSUED`, or `DISPUTED` status — may exist per
        booking at any time; attempting to create a second, or to issue while
        another live invoice exists for the booking, is rejected with
        `ERR_LIVE_INVOICE_EXISTS`."

        Design: Corner/validations/live_invoice_uniqueness_blocks_second_draft
        """
        ctx = setup_completed_booking_with_invoice(num_claims_completed=0)
        resp = api.create_booking_invoice(
            ctx["booking"]["id"], {"pricing_variant": "FINAL"}, ctx["admin"],
        )
        validate_error(resp, "ERR_LIVE_INVOICE_EXISTS", expected_status=422)


class TestInvoiceDisputeResolveCycle:
    def test_dispute_and_resolve_flip_billing_status_in_lockstep(self, api):
        """PRD §3.8: "Dispute moves `billing_status` to `DISPUTED` but
        deliberately leaves the outstanding balance unchanged — disputed
        invoices still count toward credit utilization."
        PRD §3.8: "A `PlatformAdmin` resolves a dispute by returning the
        invoice `DISPUTED` → `ISSUED`, moving `billing_status` back to
        `INVOICED`; resolution preserves the disputed numbers, since totals
        are not recomputed, so any adjustment requires voiding and
        re-issuing."

        Design: Difficulty/non_linear_state_machine/invoice_dispute_resolve_cycle
        """
        ctx = setup_issued_invoice(num_claims_completed=2)
        invoice_id = ctx["invoice"]["id"]
        booking_id = ctx["booking"]["id"]
        total_before = ctx["invoice"]["total_cents"]
        disputed = validate_success(
            api.dispute_invoice(invoice_id, {"dispute_reason": "overcharged"}, ctx["organizer"])
        )
        assert disputed["status"] == "DISPUTED"
        assert get_booking(ctx, booking_id)["billing_status"] == "DISPUTED"
        resolved = validate_success(api.resolve_dispute(invoice_id, ctx["admin"]))
        assert resolved["status"] == "ISSUED"
        assert resolved["total_cents"] == total_before, (
            "Resolution preserves the disputed numbers; totals are not recomputed"
        )
        assert get_booking(ctx, booking_id)["billing_status"] == "INVOICED"

    def test_dispute_resolve_cycle_repeats(self, api):
        """PRD §3.8: "Dispute moves `billing_status` to `DISPUTED` but
        deliberately leaves the outstanding balance unchanged — disputed
        invoices still count toward credit utilization."
        PRD §3.8: "A `PlatformAdmin` resolves a dispute by returning the
        invoice `DISPUTED` → `ISSUED`, moving `billing_status` back to
        `INVOICED`; resolution preserves the disputed numbers, since totals
        are not recomputed, so any adjustment requires voiding and
        re-issuing."

        Design: Difficulty/non_linear_state_machine/invoice_dispute_resolve_cycle
        """
        ctx = setup_issued_invoice(num_claims_completed=2)
        invoice_id = ctx["invoice"]["id"]
        validate_success(
            api.dispute_invoice(invoice_id, {"dispute_reason": "first"}, ctx["organizer"])
        )
        validate_success(api.resolve_dispute(invoice_id, ctx["admin"]))
        second = validate_success(
            api.dispute_invoice(invoice_id, {"dispute_reason": "second"}, ctx["organizer"])
        )
        assert second["status"] == "DISPUTED"
        assert get_booking(ctx, ctx["booking"]["id"])["billing_status"] == "DISPUTED"


class TestOutstandingBalanceInvariant:
    def test_outstanding_balance_invariant_under_issue_and_void(self, api):
        """PRD §3.8: "On success, `outstanding_balance_cents` and
        `lifetime_billed_cents` each increase by `total_cents`, and the
        booking's `billing_status` moves `UNBILLED` → `INVOICED`."
        PRD §3.8: "Dispute moves `billing_status` to `DISPUTED` but
        deliberately leaves the outstanding balance unchanged — disputed
        invoices still count toward credit utilization."
        PRD §3.8: "From `DISPUTED`, the invoice's `total_cents` is subtracted
        back out of `outstanding_balance_cents` and `billing_status` returns
        to `UNBILLED`, freeing the booking to be invoiced again."

        Design: Difficulty/compensating_invariant/outstanding_balance_invariant_under_issue_and_void
        """
        ctx = setup_completed_booking_with_invoice(num_claims_completed=2)
        invoice_id = ctx["invoice"]["id"]
        total = ctx["invoice"]["total_cents"]
        ob_pre = get_account(ctx)["outstanding_balance_cents"]
        assert ob_pre == 0
        validate_success(api.issue_invoice(invoice_id, ctx["admin"]))
        ob_mid = get_account(ctx)["outstanding_balance_cents"]
        assert ob_mid == ob_pre + total, (
            f"Issuing adds total_cents: expected {ob_pre + total}, got {ob_mid}"
        )
        validate_success(
            api.dispute_invoice(invoice_id, {"dispute_reason": "d"}, ctx["organizer"])
        )
        assert get_account(ctx)["outstanding_balance_cents"] == ob_mid, (
            "Dispute leaves the outstanding balance unchanged"
        )
        validate_success(api.void_invoice(invoice_id, ctx["admin"]))
        ob_post = get_account(ctx)["outstanding_balance_cents"]
        assert ob_post == ob_pre, (
            f"Invariant violated: after issue+dispute+void, balance must return "
            f"to {ob_pre}, got {ob_post}"
        )
        assert get_booking(ctx, ctx["booking"]["id"])["billing_status"] == "UNBILLED"

    def test_outstanding_balance_restored_by_payment(self, api):
        """PRD §3.8: "On success, `outstanding_balance_cents` and
        `lifetime_billed_cents` each increase by `total_cents`, and the
        booking's `billing_status` moves `UNBILLED` → `INVOICED`."
        PRD §3.8: "Payment recording moves the invoice `ISSUED` → `PAID`,
        subtracts `total_cents` from `outstanding_balance_cents`, and moves
        `billing_status` to `PAID`."

        Design: Difficulty/compensating_invariant/outstanding_balance_invariant_under_issue_and_void
        """
        ctx = setup_issued_invoice(num_claims_completed=2)
        invoice_id = ctx["invoice"]["id"]
        total = ctx["invoice"]["total_cents"]
        assert get_account(ctx)["outstanding_balance_cents"] == total
        validate_success(api.record_payment(invoice_id, ctx["admin"]))
        assert get_account(ctx)["outstanding_balance_cents"] == 0
        assert get_invoice(ctx, invoice_id)["status"] == "PAID"
        assert get_booking(ctx, ctx["booking"]["id"])["billing_status"] == "PAID"
