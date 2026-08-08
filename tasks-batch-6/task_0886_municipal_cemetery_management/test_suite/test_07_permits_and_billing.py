"""Marker installation gate, payment state/amount gates, maker-checker void."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    TEST_USERS, make_registrar_headers, make_finance_officer_headers,
    setup_approved_marker, setup_issued_deed, setup_pending_deed,
    create_payment_payload,
)

REG = TEST_USERS["registrar_headers"]
FIN = TEST_USERS["finance_officer_headers"]
GF = TEST_USERS["grounds_foreman_headers"]


# ── Corner: state_machines / install_marker_without_completed_interment ──

def test_install_marker_without_completed_interment_rejected(api):
    """PRD §3.5: "A GroundsForeman records installation, moving APPROVED to INSTALLED,
    only when the MARKER_FOUNDATION invoice has been paid (otherwise
    ERR_INVOICE_UNPAID) and the plot has an interment whose operational_status is
    COMPLETED (otherwise ERR_NO_COMPLETED_INTERMENT)."

    Design: Corner/state_machines/install_marker_without_completed_interment
    """
    r = setup_approved_marker(marker_type="FLAT", pay_foundation=True)
    res = api.install_marker_permit(r["permit"]["id"], GF)
    validate_error(res, "ERR_NO_COMPLETED_INTERMENT")


# ── Corner: validations / pay_already_paid_invoice_not_open ──

def test_pay_already_paid_invoice_not_open(api):
    """PRD §3.7: "The invoice must be in ISSUED state to accept a payment; a payment
    attempted against an invoice that is not ISSUED is rejected with
    ERR_INVOICE_NOT_OPEN."

    Design: Corner/validations/pay_already_paid_invoice_not_open
    """
    r = setup_issued_deed()  # DEED_SALE invoice is already PAID
    invoice = get_success_data(api.get_invoice(r["sale_invoice_id"], FIN))
    res = api.create_payment(
        create_payment_payload(r["sale_invoice_id"], invoice["total_cents"]), FIN)
    validate_error(res, "ERR_INVOICE_NOT_OPEN")


# ── Corner: validations / payment_amount_mismatch_rejected ──

def test_payment_amount_mismatch_rejected(api):
    """PRD §3.7: "The tendered amount_cents must equal the invoice's total_cents
    exactly, otherwise ERR_PAYMENT_AMOUNT_MISMATCH."

    Design: Corner/validations/payment_amount_mismatch_rejected
    """
    r = setup_pending_deed()  # DEED_SALE invoice ISSUED, total 1222500
    res = api.create_payment(create_payment_payload(r["sale_invoice_id"], 100), FIN)
    validate_error(res, "ERR_PAYMENT_AMOUNT_MISMATCH")


# ── Corner: rbac / invoice_void_maker_checker_segregation ──

def test_void_invoice_by_issuing_user_segregation(api):
    """PRD §3.7: "the acting officer's X-User-ID must differ from the invoice's
    issued_by_user_id, otherwise ERR_SEGREGATION_OF_DUTIES". PRD §2.6: "Every invoice
    also records issued_by_user_id — the X-User-ID of the actor whose action generated
    it".

    Design: Corner/rbac/invoice_void_maker_checker_segregation
    """
    r = setup_pending_deed(deed_headers=make_registrar_headers("op-77"))
    res = api.void_invoice(r["sale_invoice_id"], make_finance_officer_headers("op-77"))
    validate_error(res, "ERR_SEGREGATION_OF_DUTIES")
