"""Bills, package discount tiers, payments, refunds, invoices (PRD §3.9, §2.8)."""
from __future__ import annotations

import pytest

from test_helpers import (
    TEST_USERS,
    create_bill,
    create_drug,
    dispense_prescription,
    get_success_data,
    issue_bill,
    issue_invoice,
    make_prescription_item,
    pay_bill,
    payment_payload,
    recompute_bill,
    request_refund,
    setup_approved_prescription,
    setup_visit_consult_done,
    setup_visit_through_paid_bill,
    setup_visit_in_consult,
    setup_visit_with_finalized_treatment,
    unique_event_id,
    validate_error,
    validate_success,
)


class TestBillCreate:
    def test_bill_created_in_draft(self, api):
        """PRD §3.9: 'The new bill carries a line_items array (initially
        empty ...), ... a deposit_applied_cents of 0, a
        provisional_total_cents of 0, ... a paid_amount_cents of 0,
        a refund_amount_cents of 0, an invoice_no of null, and a
        status of DRAFT.'"""
        owner, pet, visit = setup_visit_in_consult()
        bill = create_bill(visit_id=visit["id"])
        assert bill["status"] == "DRAFT"
        assert bill["line_items"] == []
        assert bill["deposit_applied_cents"] == 0
        assert bill["provisional_total_cents"] == 0
        assert bill["paid_amount_cents"] == 0
        assert bill["refund_amount_cents"] == 0
        assert bill.get("invoice_no") in (None, "")


class TestBillIssueAndDeposit:
    def test_issue_applies_deposit_capped_at_gross(self, api, cashier_headers):
        """PRD §3.9: 'On entry to ISSUED, the system applies the deposit:
        deposit_applied_cents is set to the smaller of the owner's
        deposit_balance_cents and the gross-after-discount, and the
        owner's deposit_balance_cents is decremented by that same
        applied amount.'"""
        # Deposit larger than the bill total → cap at total.
        owner, pet, visit, tr = setup_visit_consult_done(deposit_cents=200_000)
        bill = create_bill(visit_id=visit["id"])
        bill = recompute_bill(bill_id=bill["id"])
        gross = sum(li["line_total_cents"] for li in bill["line_items"])
        assert gross >= 0
        bill = issue_bill(bill_id=bill["id"])
        assert bill["status"] == "ISSUED"
        # deposit_applied_cents should equal min(deposit, gross-after-discount-of-no-package=gross)
        assert bill["deposit_applied_cents"] == min(200_000, gross)
        # Owner deposit decreases by the same amount.
        owner_after = get_success_data(
            api.get_owner(owner["id"], TEST_USERS["cashier_headers"])
        )
        assert owner_after["deposit_balance_cents"] == (
            owner["deposit_balance_cents"] - bill["deposit_applied_cents"]
        )


class TestPartialAndFullPayment:
    def test_partial_payment_transitions_to_partially_paid(self, api):
        """PRD §3.9: 'A payment whose amount is strictly positive but
        whose cumulative paid-amount has not yet reached the
        gross-after-discount minus the deposit-applied amount transitions
        the bill from ISSUED to PARTIALLY_PAID and increments
        paid_amount_cents by the event amount.'"""
        # Build a CONSULT line with significant cost via a finalized
        # treatment record + dispense, so amount_due is large enough
        # for a partial-vs-full split. The CONSULT default unit_price
        # is implementation-defined, so we accumulate enough by
        # finalizing several lab reports too.
        owner, pet, visit, tr = setup_visit_consult_done(deposit_cents=0)
        bill = create_bill(visit_id=visit["id"])
        bill = recompute_bill(bill_id=bill["id"])
        bill = issue_bill(bill_id=bill["id"])
        amount_due = bill["provisional_total_cents"]
        # Choose a partial amount strictly less than amount_due.
        # If amount_due is 0 or 1, the partial branch cannot be exercised
        # without making the implementation pin specific unit prices.
        # PRD §3.9 names the rule but does not pin unit_price_cents for
        # CONSULT lines, so the test instead pins the partial branch
        # by paying half of any positive amount_due.
        assert amount_due >= 2, (
            "amount_due must be at least 2 cents for the partial path "
            "(PRD §3.9 names the partial-payment branch as a regime that "
            "applies whenever cumulative paid < amount_due)"
        )
        partial = amount_due // 2
        bill = pay_bill(bill_id=bill["id"], amount_cents=partial)
        assert bill["status"] == "PARTIALLY_PAID"
        assert bill["paid_amount_cents"] == partial

    def test_full_payment_transitions_to_paid(self, api):
        """PRD §3.9: 'A payment whose cumulative paid-amount reaches the
        same threshold (the gross-after-discount minus the deposit-applied
        amount) transitions the bill into PAID from either ISSUED
        (single-payment path) or PARTIALLY_PAID (final installment path).'"""
        owner, pet, visit, tr = setup_visit_consult_done(deposit_cents=0)
        bill = create_bill(visit_id=visit["id"])
        bill = recompute_bill(bill_id=bill["id"])
        bill = issue_bill(bill_id=bill["id"])
        amount_due = bill["provisional_total_cents"]
        bill = pay_bill(bill_id=bill["id"], amount_cents=amount_due)
        assert bill["status"] == "PAID"


class TestPaymentIdempotency:
    def test_duplicate_event_id_is_rejected(self, api, platform_admin_headers):
        """PRD §3.9: 'Payments arrive through the payment event endpoint
        with the bill_id, the amount_cents, and an event_id; the endpoint
        is idempotent on event_id, and a duplicate event_id is rejected
        with ERR_DUPLICATE_EVENT.'"""
        owner, pet, visit, tr = setup_visit_consult_done(deposit_cents=0)
        bill = create_bill(visit_id=visit["id"])
        bill = recompute_bill(bill_id=bill["id"])
        bill = issue_bill(bill_id=bill["id"])
        amount_due = bill["provisional_total_cents"]
        assert amount_due >= 2, (
            "amount_due must be at least 2 for this idempotency test "
            "(see PRD §3.9 partial-payment regime)"
        )
        ev_id = unique_event_id("evt-dup")
        first = pay_bill(bill_id=bill["id"], amount_cents=1, event_id=ev_id)
        # Replay with the same event_id and the same amount.
        res = api.post_payment(
            payment_payload(
                bill_id=bill["id"], amount_cents=1, event_id=ev_id,
            ),
            platform_admin_headers,
        )
        validate_error(res, "ERR_DUPLICATE_EVENT")


class TestRefundCap:
    def test_refund_exceeding_paid_rejected(self, api):
        """PRD §3.9: 'the precondition is that the cumulative refund —
        the proposed amount_cents plus the existing refund_amount_cents
        — must not exceed paid_amount_cents, otherwise the request is
        rejected with ERR_REFUND_EXCEEDS_PAID.'"""
        owner, pet, visit, tr = setup_visit_consult_done(deposit_cents=0)
        bill = create_bill(visit_id=visit["id"])
        bill = recompute_bill(bill_id=bill["id"])
        bill = issue_bill(bill_id=bill["id"])
        bill = pay_bill(bill_id=bill["id"], amount_cents=bill["provisional_total_cents"])
        assert bill["status"] == "PAID"
        paid = bill["paid_amount_cents"]
        # Request a refund larger than paid.
        from test_helpers import refund_request_payload
        res = api.refund_bill(
            bill["id"],
            refund_request_payload(amount_cents=paid + 1, reason="overrefund"),
            TEST_USERS["cashier_headers"],
        )
        validate_error(res, "ERR_REFUND_EXCEEDS_PAID")


class TestInvoiceNumberFormat:
    def test_issue_invoice_sets_invoice_no(self, api):
        """PRD §3.9: 'The cashier issues an invoice from PAID by calling
        the issue-invoice action; on success, invoice_no is set to a
        string of the form INV-YYYYMMDD-{seq6} (six-digit zero-padded
        sequence per day) and the bill transitions to INVOICED.'"""
        ctx = setup_visit_through_paid_bill(deposit_cents=0)
        bill = ctx["bill"]
        assert bill["status"] == "PAID"
        bill_invoiced = issue_invoice(bill_id=bill["id"])
        assert bill_invoiced["status"] == "INVOICED"
        invoice_no = bill_invoiced.get("invoice_no") or ""
        # PRD pins shape "INV-YYYYMMDD-{seq6}". Verify prefix and the
        # number of segments / segment lengths only — the exact day is
        # determined by the test clock.
        parts = invoice_no.split("-")
        assert len(parts) == 3, (
            f"invoice_no must be of the form INV-YYYYMMDD-{{seq6}}, got {invoice_no!r}"
        )
        assert parts[0] == "INV"
        assert len(parts[1]) == 8 and parts[1].isdigit()
        assert len(parts[2]) == 6 and parts[2].isdigit()
