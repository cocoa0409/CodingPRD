"""Invoice lifecycle and payment math tests."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId,
    create_client_with_agreement, create_batch,
    batch_in_indexing, index_document,
    scan_and_commit, batch_in_scanning,
    get_invoice_id_for_batch, get_invoice,
    make_intake_clerk_headers, make_qa_reviewer_headers, make_billing_clerk_headers,
    CLERK, QA, BILL,
)


class TestInvoiceVoidThenIssueReturnsInvalidState:
    """Corner: invoice_void_then_issue_returns_invalid_state."""

    def test_voided_draft_cannot_be_issued(self, api):
        """PRD §3.6: "A clerk may also void a `DRAFT` invoice with a recorded
        `void_reason`, ending its lifecycle as `VOID`."

        Design: Corner/state_machines/invoice_void_then_issue_returns_invalid_state
        """
        client, _ = create_client_with_agreement(name="VoidInv Co", hipaa_covered=False)
        batch = create_batch(client["id"])
        inv_id = get_invoice_id_for_batch(batch["id"])
        get_success_data(api_client.void_invoice(
            inv_id, {"void_reason": "duplicate batch"}, make_billing_clerk_headers(BILL),
        ))
        resp = api_client.issue_invoice(inv_id, make_billing_clerk_headers(BILL))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        inv = get_invoice(inv_id)
        assert inv["status"] == "VOID"
        assert inv["void_reason"] == "duplicate batch"


class TestErrorPaymentOverpayAndPartialThenFull:
    """Corner: error_payment_overpay_and_partial_then_full."""

    def _setup_issued_invoice_4500(self):
        """Full pipeline to DELIVERED with a single 100-page STANDARD doc.
        Issue immediately inside free storage window; total = 4500."""
        client, _ = create_client_with_agreement(
            name="Pay Co", hipaa_covered=False,
            price_tier="STANDARD", rush_multiplier=1.75,
            storage_free_days=10, storage_daily_rate_cents=55,
            retention_days=30, max_boxes_per_batch=5,
        )
        ctx = batch_in_indexing(
            [{"doc_type": "CONTRACT", "pages": 100, "ocr_confidence": 95}],
            client_id=client["id"],
        )
        get_success_data(index_document(ctx["documents"][0]["id"], title="T1", record_date="2026-01-01", subject="S1", ocr_text_ref="ocr://t1"))
        get_success_data(api_client.deliver_batch(ctx["batch"]["id"], make_qa_reviewer_headers(QA)))
        inv_id = get_invoice_id_for_batch(ctx["batch"]["id"])
        get_success_data(api_client.issue_invoice(inv_id, make_billing_clerk_headers(BILL)))
        return ctx, inv_id

    def test_overpay_partial_then_full(self, api):
        """PRD §3.6: "Payments against an `ISSUED` or `PARTIALLY_PAID` invoice
        carry `amount_cents` of at least 1 and no more than the outstanding
        balance (`total_cents` minus `amount_paid_cents`); an overpayment is
        rejected with `ERR_PAYMENT_EXCEEDS_BALANCE` (HTTP 422), and a payment
        attempted on a `DRAFT` or `VOID` invoice is rejected with
        `ERR_INVOICE_NOT_ISSUED` (HTTP 409). Each accepted payment adds
        `amount_cents` to `amount_paid_cents`; a payment smaller than the
        outstanding balance moves the invoice to `PARTIALLY_PAID`, and one
        exactly equal to the outstanding balance moves it to `PAID`."

        Design: Corner/errors/error_payment_overpay_and_partial_then_full
        """
        _ctx, inv_id = self._setup_issued_invoice_4500()
        inv = get_invoice(inv_id)
        assert inv["total_cents"] == 4500

        # Overpay 4501 on a 4500 balance: rejected.
        resp = api_client.create_payment(inv_id, {"amount_cents": 4501}, make_billing_clerk_headers(BILL))
        validate_error(resp, ApiErrorId.ERR_PAYMENT_EXCEEDS_BALANCE, expected_status=422)

        # Partial 2000: ISSUED -> PARTIALLY_PAID
        ok1 = api_client.create_payment(inv_id, {"amount_cents": 2000}, make_billing_clerk_headers(BILL))
        inv1 = validate_success(ok1, expected_status=200)
        assert inv1["status"] == "PARTIALLY_PAID"
        assert inv1["amount_paid_cents"] == 2000

        # Final 2500: -> PAID
        ok2 = api_client.create_payment(inv_id, {"amount_cents": 2500}, make_billing_clerk_headers(BILL))
        inv2 = validate_success(ok2, expected_status=200)
        assert inv2["status"] == "PAID"
        assert inv2["amount_paid_cents"] == 4500


class TestErrorPaymentOnDraftInvoice:
    """Corner: error_payment_on_draft_invoice."""

    def test_payment_on_draft_rejected(self, api):
        """PRD §3.6: "a payment attempted on a `DRAFT` or `VOID` invoice is
        rejected with `ERR_INVOICE_NOT_ISSUED` (HTTP 409)"

        Design: Corner/errors/error_payment_on_draft_invoice
        """
        client, _ = create_client_with_agreement(name="Draft Co", hipaa_covered=False)
        batch = create_batch(client["id"])
        inv_id = get_invoice_id_for_batch(batch["id"])
        resp = api_client.create_payment(inv_id, {"amount_cents": 100}, make_billing_clerk_headers(BILL))
        validate_error(resp, ApiErrorId.ERR_INVOICE_NOT_ISSUED, expected_status=409)
        inv = get_invoice(inv_id)
        assert inv["status"] == "DRAFT"
        assert inv["amount_paid_cents"] == 0


class TestErrorIssueBeforeDelivery:
    """Corner: error_issue_before_delivery."""

    def test_issue_while_batch_scanning_rejected(self, api):
        """PRD §3.6: "A `BillingClerk` issues the invoice — permitted only
        once the batch is `DELIVERED`, `DISPOSITION_PENDING`, or `CLOSED`, and
        only from `DRAFT` — which stamps `issued_at` from the clock and
        freezes both subtotals."

        Design: Corner/errors/error_issue_before_delivery
        """
        client, _ = create_client_with_agreement(name="Early Co", hipaa_covered=False)
        ctx = batch_in_scanning(
            [{"doc_type": "OTHER", "pages": 50, "ocr_confidence": 95}],
            client_id=client["id"],
        )
        inv_id = get_invoice_id_for_batch(ctx["batch"]["id"])
        resp = api_client.issue_invoice(inv_id, make_billing_clerk_headers(BILL))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        inv = get_invoice(inv_id)
        assert inv.get("issued_at") is None
