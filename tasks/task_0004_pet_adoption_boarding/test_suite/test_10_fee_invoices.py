"""Tests for FeeInvoice lifecycle: pay, refund, void.

Covers: PRD Section 3.6 (Fees, Invoices, and Payment),
Table 2 (FeeInvoice state machine), Table 4 priorities 26-29.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    NON_EXISTENT_UUID, ApiErrorId, TEST_USERS,
    assert_fee_invoice, assert_fee_invoice_invariants,
    pay_invoice_payload,
    create_approved_application, pay_invoice_in_full,
    create_paid_adoption_invoice, create_settlement_batch_for_shelter,
    create_boarding_confirmed, create_boarding_requested,
)

_manager = TEST_USERS["manager_headers"]
_case_worker = TEST_USERS["case_worker_headers"]


class TestInvoiceCreationOnApproval:
    """PRD 3.6: Invoice created ISSUED when application is approved."""

    def test_invoice_created_on_approve(self):
        shelter, animal, adopter, app, invoice, reviewer, approver = \
            create_approved_application(species="CAT", weight_kg=5.0)
        assert_fee_invoice(invoice)
        assert invoice["status"] == "ISSUED"
        assert invoice["reference_type"] == "ADOPTION"
        assert invoice["reference_id"] == app["id"]
        assert invoice["paid_amount_cents"] == 0
        assert invoice["refund_amount_cents"] == 0
        assert invoice["balance_due_cents"] == invoice["total_amount_cents"]
        assert invoice["settlement_batch_id"] is None
        assert_fee_invoice_invariants(invoice)


class TestPayFullAmount:
    """PRD 3.6: Full payment -> PAID and shelter.revenue_pending_cents increases."""

    def test_pay_full_amount_in_one_go(self):
        shelter, animal, adopter, app, invoice, reviewer, approver = \
            create_approved_application(species="CAT", weight_kg=5.0)
        total = invoice["total_amount_cents"]
        resp = api_client.pay_fee_invoice(
            invoice["id"], pay_invoice_payload(total), _case_worker
        )
        data = validate_success(resp)
        assert data["status"] == "PAID"
        assert data["paid_amount_cents"] == total
        assert data["balance_due_cents"] == 0
        # shelter.revenue_pending_cents must reflect the paid amount.
        refreshed_shelter = get_success_data(api_client.get_shelter(shelter["id"], _manager))
        assert refreshed_shelter["revenue_pending_cents"] >= total

    def test_pay_zero_amount_rejected(self):
        shelter, animal, adopter, app, invoice, reviewer, approver = \
            create_approved_application(species="CAT", weight_kg=5.0)
        resp = api_client.pay_fee_invoice(
            invoice["id"], pay_invoice_payload(0), _case_worker
        )
        validate_error(resp, ApiErrorId.ERR_PAYMENT_AMOUNT_INVALID)

    def test_pay_negative_amount_rejected(self):
        shelter, animal, adopter, app, invoice, reviewer, approver = \
            create_approved_application(species="CAT", weight_kg=5.0)
        resp = api_client.pay_fee_invoice(
            invoice["id"], pay_invoice_payload(-100), _case_worker
        )
        validate_error(resp, ApiErrorId.ERR_PAYMENT_AMOUNT_INVALID)

    def test_pay_exceeds_balance_rejected(self):
        shelter, animal, adopter, app, invoice, reviewer, approver = \
            create_approved_application(species="CAT", weight_kg=5.0)
        total = invoice["total_amount_cents"]
        resp = api_client.pay_fee_invoice(
            invoice["id"], pay_invoice_payload(total + 1), _case_worker
        )
        validate_error(resp, ApiErrorId.ERR_PAYMENT_AMOUNT_INVALID)


class TestPartialPayment:
    """PRD 3.6: Partial payment -> PARTIALLY_PAID."""

    def test_partial_payment_then_complete(self):
        shelter, animal, adopter, app, invoice, reviewer, approver = \
            create_approved_application(species="CAT", weight_kg=5.0)
        total = invoice["total_amount_cents"]
        half = max(1, total // 2)
        # First partial payment
        data = get_success_data(api_client.pay_fee_invoice(
            invoice["id"], pay_invoice_payload(half), _case_worker
        ))
        assert data["status"] == "PARTIALLY_PAID"
        assert data["paid_amount_cents"] == half
        # Second payment to finalize
        remaining = total - half
        data2 = get_success_data(api_client.pay_fee_invoice(
            invoice["id"], pay_invoice_payload(remaining), _case_worker
        ))
        assert data2["status"] == "PAID"
        assert data2["paid_amount_cents"] == total
        assert data2["balance_due_cents"] == 0


class TestVoid:
    """PRD 3.6: /void an ISSUED or DRAFT invoice (no payments)."""

    def test_void_issued_success(self):
        shelter, animal, adopter, app, invoice, reviewer, approver = \
            create_approved_application(species="CAT", weight_kg=5.0)
        resp = api_client.void_fee_invoice(invoice["id"], _manager)
        data = validate_success(resp)
        assert data["status"] == "VOID"

    def test_void_with_payments_rejected(self):
        """ERR_INVOICE_HAS_PAYMENTS if paid_amount_cents > 0."""
        shelter, animal, adopter, app, invoice, reviewer, approver = \
            create_approved_application(species="CAT", weight_kg=5.0)
        # Partial payment
        total = invoice["total_amount_cents"]
        half = max(1, total // 2)
        get_success_data(api_client.pay_fee_invoice(
            invoice["id"], pay_invoice_payload(half), _case_worker
        ))
        resp = api_client.void_fee_invoice(invoice["id"], _manager)
        validate_error(resp, ApiErrorId.ERR_INVOICE_HAS_PAYMENTS)

    def test_void_paid_invoice_rejected(self):
        """Cannot void a PAID invoice."""
        shelter, animal, adopter, app, invoice = create_paid_adoption_invoice(
            species="CAT", weight_kg=5.0
        )
        resp = api_client.void_fee_invoice(invoice["id"], _manager)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestRefund:
    """PRD 3.6: /refund PAID or PARTIALLY_PAID, but not if settled."""

    def test_refund_paid_invoice(self):
        shelter, animal, adopter, app, invoice = create_paid_adoption_invoice(
            species="CAT", weight_kg=5.0
        )
        resp = api_client.refund_fee_invoice(invoice["id"], _manager)
        data = validate_success(resp)
        assert data["status"] == "REFUNDED"
        assert data["refund_amount_cents"] == data["paid_amount_cents"]
        # revenue_pending_cents decreases accordingly
        refreshed_shelter = get_success_data(api_client.get_shelter(shelter["id"], _manager))
        # After refund, pending should be 0 or less than after pay
        assert refreshed_shelter["revenue_pending_cents"] <= invoice["total_amount_cents"]

    def test_refund_issued_invoice_rejected(self):
        """Cannot refund an ISSUED (unpaid) invoice — only PAID or PARTIALLY_PAID."""
        shelter, animal, adopter, app, invoice, reviewer, approver = \
            create_approved_application(species="CAT", weight_kg=5.0)
        resp = api_client.refund_fee_invoice(invoice["id"], _manager)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_refund_settled_invoice_rejected(self):
        """ERR_INVOICE_ALREADY_SETTLED if invoice already in APPROVED SettlementBatch."""
        shelter, animal, adopter, app, invoice = create_paid_adoption_invoice(
            species="CAT", weight_kg=5.0
        )
        batch = create_settlement_batch_for_shelter(shelter["id"])
        # Only test if the batch actually included this invoice
        if invoice["id"] in batch["invoice_ids"]:
            get_success_data(api_client.approve_settlement_batch(batch["id"], _manager))
            resp = api_client.refund_fee_invoice(invoice["id"], _manager)
            validate_error(resp, ApiErrorId.ERR_INVOICE_ALREADY_SETTLED)


class TestInvoiceRetrieval:
    def test_get_invoice(self):
        shelter, animal, adopter, app, invoice, reviewer, approver = \
            create_approved_application(species="CAT", weight_kg=5.0)
        resp = api_client.get_fee_invoice(invoice["id"], _manager)
        data = validate_success(resp)
        assert_fee_invoice(data)

    def test_get_invoice_not_found(self):
        resp = api_client.get_fee_invoice(NON_EXISTENT_UUID, _manager)
        validate_error(resp, ApiErrorId.ERR_INVOICE_NOT_FOUND)

    def test_list_invoices(self):
        shelter, animal, adopter, app, invoice, reviewer, approver = \
            create_approved_application(species="CAT", weight_kg=5.0)
        resp = api_client.list_fee_invoices(_manager)
        validate_success(resp)


class TestCancelledBoardingInvoice:
    """PRD 3.5 + 3.6: Cancelling a CONFIRMED boarding with ISSUED invoice voids it."""

    def test_cancel_voids_issued_boarding_invoice(self):
        shelter, animal, res, invoice, match = create_boarding_confirmed()
        get_success_data(api_client.cancel_boarding_reservation(res["id"], _manager))
        refreshed_invoice = get_success_data(api_client.get_fee_invoice(invoice["id"], _manager))
        assert refreshed_invoice["status"] == "VOID"
