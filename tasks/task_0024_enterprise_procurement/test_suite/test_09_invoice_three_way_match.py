"""Invoice three-way match, tax compliance, override, approval (PRD §3.9)."""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_invoice,
    assert_invoice,
    create_invoice_payload,
    make_supplier_headers,
    match_invoice,
    override_invoice_payload,
    reject_invoice_payload,
    setup_invoice_match_ready,
    setup_receipts_for_invoice,
    submit_invoice,
    validate_error,
    validate_success,
)


# ===========================================================================
# Invoice submission (PRD §3.9)
# ===========================================================================
class TestInvoiceSubmit:
    def test_invoice_submitted_starts_in_submitted(self, api):
        """PRD §3.9: "The invoice begins in SUBMITTED."

        Claim: a freshly created invoice has status=SUBMITTED.
        """
        setup = setup_invoice_match_ready()
        invoice = setup["invoice"]
        assert_invoice(invoice)
        assert invoice["status"] == "SUBMITTED"


# ===========================================================================
# Three-way match success (PRD §3.9)
# ===========================================================================
class TestInvoiceMatch:
    def test_invoice_matches_when_all_three_pass(self, api, finance_headers):
        """PRD §3.9: "The overall three-way match passes when quantity,
        amount, and tax compliance all pass; the invoice transitions
        from SUBMITTED to MATCHED and matching_result is populated as
        an object containing quantity_match, amount_match, tax_compliant,
        and a deltas sub-object capturing the underlying numbers."

        Claim: invoiced_quantity == received, invoiced_amount == pro-rata,
        tax_rate=0.13 within tolerance → invoice MATCHED with
        matching_result populated.
        """
        # Default fixture: invoiced_amount equals PO total (10 units * 100_000 = 1_000_000),
        # tax = round(1_000_000 - 1_000_000/1.13) = 115_044.
        # Use precise tax_amount_cents to clear tolerance.
        # tax_expected = 1_000_000 - round(1_000_000/1.13) = 1_000_000 - 884_956 = 115_044
        setup = setup_invoice_match_ready(
            quantity=10,
            invoiced_quantity=10,
            invoiced_amount_cents=1_000_000,
            tax_amount_cents=115_044,
            tax_rate_declared=0.13,
        )
        result = match_invoice(setup["invoice"]["id"])
        assert result["status"] == "MATCHED"
        mr = result.get("matching_result")
        assert mr is not None
        assert mr["quantity_match"] is True
        assert mr["amount_match"] is True
        assert mr["tax_compliant"] is True

    def test_quantity_mismatch_routes_to_exception(self, api, finance_headers):
        """PRD §3.9: "If any of the three component checks fails the
        invoice transitions to EXCEPTION instead, matching_result is
        populated with the deltas, and one of two errors is reported:
        ... a quantity-or-amount tolerance failure surfaces as
        ERR_THREE_WAY_MATCH_FAILED."

        Claim: invoiced_quantity off by >2% (qty_delta_pct > 0.02) yields
        Invoice in EXCEPTION and ERR_THREE_WAY_MATCH_FAILED.
        """
        # received_qty=100, invoiced_qty=90 → delta 0.10.
        # PO total: 11_300; quantity=100 → per-unit 113. Use price 113.
        setup = setup_invoice_match_ready(
            quote_specs=[(113, 90.0), (130, 80.0), (140, 70.0)],
            quantity=100,
            invoiced_quantity=90,
            invoiced_amount_cents=10_170,
            tax_amount_cents=1_170,
            tax_rate_declared=0.13,
        )
        res = api.match_invoice(setup["invoice"]["id"], TEST_USERS["finance_headers"])
        validate_error(res, ApiErrorId.ERR_THREE_WAY_MATCH_FAILED.value)
        # Invoice should now be in EXCEPTION.
        invoice = validate_success(
            api.get_invoice(setup["invoice"]["id"], TEST_USERS["finance_headers"]), 200
        )
        assert invoice["status"] == "EXCEPTION"


# ===========================================================================
# Tax compliance (PRD §3.9, priority 15)
# ===========================================================================
class TestInvoiceTaxCompliance:
    def test_unallowed_tax_rate_yields_tax_noncompliant(
        self, api, finance_headers
    ):
        """PRD §3.9: "Tax compliance requires both that the tax delta is
        at most TAX_TOLERANCE_CENTS, which is one cent, and that
        tax_rate_declared is one of the values in ALLOWED_TAX_RATES:
        0.06, 0.09, or 0.13. ... a tax-side failure — tax_rate_declared
        not in the allowed set, or tax_amount_cents outside the tolerance
        — surfaces as ERR_TAX_NONCOMPLIANT".

        Claim: tax_rate_declared = 0.10 (not in {0.06, 0.09, 0.13})
        yields ERR_TAX_NONCOMPLIANT.
        """
        setup = setup_invoice_match_ready(
            invoiced_amount_cents=1_000_000,
            tax_amount_cents=90_909,
            tax_rate_declared=0.10,
        )
        res = api.match_invoice(setup["invoice"]["id"], TEST_USERS["finance_headers"])
        validate_error(res, ApiErrorId.ERR_TAX_NONCOMPLIANT.value)

    def test_tax_priority_over_qty_amount_match(self, api, finance_headers):
        """PRD §3.9: "(Per §2.8, the tax check is evaluated before the
        quantity-and-amount check, so a tax-noncompliant invoice that
        also blows the quantity tolerance is reported as
        ERR_TAX_NONCOMPLIANT.)"

        Claim: simultaneous tax-noncompliant + quantity-mismatch yields
        ERR_TAX_NONCOMPLIANT (priority 15 < priority 16).
        """
        setup = setup_invoice_match_ready(
            quote_specs=[(113, 90.0), (130, 80.0), (140, 70.0)],
            quantity=100,
            invoiced_quantity=90,           # quantity blow
            invoiced_amount_cents=10_170,
            tax_amount_cents=1_017,         # would be off-tolerance for 0.10 rate
            tax_rate_declared=0.10,         # also disallowed
        )
        res = api.match_invoice(setup["invoice"]["id"], TEST_USERS["finance_headers"])
        validate_error(res, ApiErrorId.ERR_TAX_NONCOMPLIANT.value)


# ===========================================================================
# GM override (PRD §3.9)
# ===========================================================================
class TestInvoiceOverride:
    def test_gm_override_advances_exception_to_matched(
        self, api, finance_headers, gm_headers
    ):
        """PRD §3.9: "A GeneralManager may override an EXCEPTION invoice.
        The override supplies a justification; on success the invoice
        moves from EXCEPTION to MATCHED, the existing matching_result is
        augmented with an override_by field naming the overriding manager,
        and the override forces the matched outcome regardless of the
        underlying tolerances."

        Claim: GM override on EXCEPTION invoice flips status to MATCHED
        with override_by populated.
        """
        # Force EXCEPTION via quantity mismatch.
        setup = setup_invoice_match_ready(
            quote_specs=[(113, 90.0), (130, 80.0), (140, 70.0)],
            quantity=100,
            invoiced_quantity=90,
            invoiced_amount_cents=10_170,
            tax_amount_cents=1_170,
            tax_rate_declared=0.13,
        )
        api.match_invoice(setup["invoice"]["id"], finance_headers)
        result = validate_success(
            api.override_invoice(
                setup["invoice"]["id"],
                override_invoice_payload(justification="Reconciled with vendor"),
                gm_headers,
            ),
            200,
        )
        assert result["status"] == "MATCHED"
        assert result["matching_result"].get("override_by") is not None


# ===========================================================================
# Reject EXCEPTION invoice (PRD §3.9)
# ===========================================================================
class TestInvoiceReject:
    def test_reject_exception_invoice_advances_to_rejected(
        self, api, finance_headers
    ):
        """PRD §3.9: "A FinanceApprover may instead reject an EXCEPTION
        invoice with a reason, moving it to the terminal REJECTED."

        Claim: /invoices/{id}/reject on EXCEPTION sets status=REJECTED.
        """
        setup = setup_invoice_match_ready(
            quote_specs=[(113, 90.0), (130, 80.0), (140, 70.0)],
            quantity=100,
            invoiced_quantity=90,
            invoiced_amount_cents=10_170,
            tax_amount_cents=1_170,
            tax_rate_declared=0.13,
        )
        api.match_invoice(setup["invoice"]["id"], finance_headers)
        result = validate_success(
            api.reject_invoice(
                setup["invoice"]["id"],
                reject_invoice_payload(reason="Cannot reconcile"),
                finance_headers,
            ),
            200,
        )
        assert result["status"] == "REJECTED"


# ===========================================================================
# Approve MATCHED invoice (PRD §3.9)
# ===========================================================================
class TestInvoiceApprove:
    def test_approve_matched_invoice_advances_to_approved(
        self, api, finance_headers
    ):
        """PRD §3.9: "A MATCHED invoice is approved by a FinanceApprover
        only if its matching_result.tax_compliant is true (a
        manager-overridden invoice is treated as tax-compliant by virtue
        of the override flag). On approval the invoice moves to
        APPROVED."

        Claim: a MATCHED invoice with tax_compliant=true advances to
        APPROVED on /invoices/{id}/approve.
        """
        setup = setup_invoice_match_ready(
            quantity=10,
            invoiced_quantity=10,
            invoiced_amount_cents=1_000_000,
            tax_amount_cents=115_044,
            tax_rate_declared=0.13,
        )
        match_invoice(setup["invoice"]["id"])
        result = approve_invoice(setup["invoice"]["id"])
        assert result["status"] == "APPROVED"


# ===========================================================================
# Invoice supplier-id ownership (PRD §3.9, §2.1)
# ===========================================================================
class TestInvoiceSupplierIdentity:
    def test_supplier_can_only_submit_invoice_with_own_supplier_id(self, api):
        """PRD §3.9: "supplier_id (which must equal the purchase order's
        supplier_id)".
        PRD §2.1: "When X-User-Role is Supplier, X-User-ID is the id of
        the acting Supplier entity; ownership checks on any resource that
        references a Supplier (notably an invoice referencing
        supplier_id ...) compare the resource's foreign-key field to
        X-User-ID."

        Claim: a Supplier whose X-User-ID does not match the invoice's
        supplier_id is rejected with ERR_FORBIDDEN.
        """
        setup = setup_receipts_for_invoice(quantity=10)
        po = setup["po"]
        # Submit with a Supplier-role user whose X-User-ID is some other supplier id.
        wrong_headers = make_supplier_headers("not-the-real-supplier")
        payload = create_invoice_payload(
            purchase_order_id=po["id"],
            supplier_id=po["supplier_id"],  # body says correct supplier id
            invoiced_quantity=10,
            invoiced_amount_cents=po["total_amount_cents"],
            tax_amount_cents=115_044,
            tax_rate_declared=0.13,
        )
        res = api.create_invoice(payload, wrong_headers)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)
