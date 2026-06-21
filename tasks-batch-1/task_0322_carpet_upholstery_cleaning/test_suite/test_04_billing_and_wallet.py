"""Billing-axis tests: invoice issuance and wallet application, payment settlement
bubble-up, overpayment and void guards, the void -> billing-reset -> wallet-refund
cascade, the wallet-credit conservation invariant, and invoice-version OCC.

Covers difficulty instances transitive_cascade (void) and compensating_invariant
(wallet), plus corner state_machine / validations / cross-cutting (invoice OCC)
instances.
"""
from test_helpers import (
    validate_success,
    validate_error,
    setup_completed_job,
    setup_invoiced_job,
    setup_booked_job,
    setup_customer_with_wallet_credit,
    grant_guarantee_credit,
    create_job,
    add_room,
    quote_job,
    book_job,
    start_job,
    complete_job,
    issue_invoice,
    get_customer,
    get_job,
    get_invoice,
    make_customer_headers,
    TEST_USERS,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]
SERVICE_MANAGER = TEST_USERS["service_manager_headers"]
BILLING = TEST_USERS["billing_headers"]


def _build_wallet_credit_then_billing_job(filed_window=300):
    """Customer holds 2000 wallet credit (from a granted seed claim); then a second
    COMPLETED 1-LIGHT-room job (settled 5000) is INVOICED, applying 2000 wallet
    (net 3000), no payments. Returns (customer, invoice, job_b)."""
    base = setup_customer_with_wallet_credit()
    customer = base["customer"]
    catalog = base["catalog"]
    crew = base["crew"]
    # Second billing job on a non-overlapping window [600,720).
    job_b = create_job(customer, catalog["id"])
    add_room(job_b, customer["id"], area_label="BillRoom", area_sqft=100, soiling_level="LIGHT")
    job_b = quote_job(job_b, customer["id"])
    job_b = book_job(job_b, crew["id"], 600, 720)
    job_b = start_job(job_b)
    job_b = complete_job(job_b, 800)
    invoice = issue_invoice(job_b)
    return customer, invoice, job_b


# ─── transitive_cascade: void -> billing reset -> wallet refund ─

def test_void_invoice_resets_billing_and_refunds_wallet(api):
    """PRD §3.4: "Voiding transitions the invoice OPEN → VOID and increments its
    version. If any wallet credit was applied at issuance — that is, if
    wallet_applied_cents was greater than 0 — voiding refunds it by writing a
    WalletLedgerEntry whose delta_cents is the positive wallet_applied_cents and
    whose reason is INVOICE_REFUND."
    PRD §3.4: "Voiding is a compensation that undoes issuance: the job's
    billing_status is reset to UNBILLED and its invoice_id is cleared."

    Design: Difficulty/transitive_cascade/cascade_void_invoice_to_billing_to_wallet_refund
    """
    customer, invoice, job_b = _build_wallet_credit_then_billing_job()
    res = api.void_invoice(invoice["id"], BILLING)
    voided = validate_success(res, 200)
    assert voided["status"] == "VOID"

    job_after = get_job(job_b["id"])
    assert job_after["billing_status"] == "UNBILLED"
    assert job_after["invoice_id"] is None
    cust_after = get_customer(customer["id"])
    assert cust_after["wallet_credit_cents"] == 2000, \
        f"refund restores wallet to 2000, got {cust_after['wallet_credit_cents']}"


# ─── compensating_invariant: wallet credit conserved ──────────

def test_wallet_credit_conserved_across_invoice_then_void(api):
    """PRD §3.4: "wallet_applied_cents is the smaller of the customer's current
    wallet_credit_cents and the invoice's amount_due_cents."
    PRD §2.10: "wallet_credit_cents, which is never an independently stored number
    but always the exact sum of the signed delta_cents of every WalletLedgerEntry
    belonging to that customer."
    PRD §3.4: "voiding refunds it by writing a WalletLedgerEntry whose delta_cents
    is the positive wallet_applied_cents and whose reason is INVOICE_REFUND."

    Issuance debits 2000 (balance 2000->0); void credits +2000 (balance 0->2000):
    net change zero, balance returns to exactly 2000.

    Design: Difficulty/compensating_invariant/invariant_wallet_credit_conserved_on_invoice_then_void
    """
    customer, invoice, job_b = _build_wallet_credit_then_billing_job()
    assert invoice["wallet_applied_cents"] == 2000, \
        f"min(2000, 5000) applied, got {invoice['wallet_applied_cents']}"

    validate_success(api.void_invoice(invoice["id"], BILLING), 200)

    cust_after = get_customer(customer["id"])
    assert cust_after["wallet_credit_cents"] == 2000, \
        f"balance returns to 2000, got {cust_after['wallet_credit_cents']}"
    job_after = get_job(job_b["id"])
    assert job_after["billing_status"] == "UNBILLED"


# ─── corner: settlement bubble-up ─────────────────────────────

def test_full_payment_settles_invoice_and_bubbles_job_to_paid(api):
    """PRD §3.4: "When the cumulative APPLIED total reaches or exceeds the invoice's
    net_payable_cents, the invoice transitions OPEN → SETTLED, and that settlement
    cascades across the billing axis to set the job's billing_status to PAID."

    A 1-LIGHT-room job settles to 5000 with zero wallet; net_payable 5000; one 5000
    payment settles it.

    Design: Corner/state_machines/invoice_settles_and_bubbles_job_to_paid
    """
    ctx = setup_invoiced_job(rooms=[("Rm", 100, "LIGHT")])
    invoice = ctx["invoice"]
    assert invoice["net_payable_cents"] == 5000, \
        f"net_payable should be 5000 (zero wallet), got {invoice['net_payable_cents']}"

    res = api.record_payment(invoice["id"],
                             {"amount_cents": 5000, "method": "CARD",
                              "expected_invoice_version": invoice["version"]},
                             BILLING)
    validate_success(res, 201)

    inv_after = get_invoice(invoice["id"])
    assert inv_after["status"] == "SETTLED"
    job_after = get_job(ctx["job"]["id"])
    assert job_after["billing_status"] == "PAID"


# ─── corner: validations on billing ───────────────────────────

def test_overpayment_rejected(api):
    """PRD §3.4: "A payment may not exceed the invoice's remaining net balance —
    that is, amount_cents may be no larger than net_payable_cents minus the
    already-paid amount_paid_cents; an overpayment is rejected with ERR_OVERPAYMENT
    (HTTP 402)."

    Design: Corner/validations/overpayment_rejected
    """
    ctx = setup_invoiced_job(rooms=[("Rm", 100, "LIGHT")])
    invoice = ctx["invoice"]
    res = api.record_payment(invoice["id"],
                             {"amount_cents": 6000, "method": "CASH",
                              "expected_invoice_version": invoice["version"]},
                             BILLING)
    validate_error(res, "ERR_OVERPAYMENT", expected_status=402)


def test_void_invoice_with_payment_rejected(api):
    """PRD §3.4: "Voiding requires the invoice's amount_paid_cents to be exactly 0;
    an invoice that already carries at least one APPLIED payment cannot be voided
    and the attempt is rejected with ERR_INVOICE_HAS_PAYMENTS."

    Design: Corner/validations/void_invoice_with_payment_rejected
    """
    ctx = setup_invoiced_job(rooms=[("Rm", 100, "LIGHT")])
    invoice = ctx["invoice"]
    validate_success(api.record_payment(invoice["id"],
                     {"amount_cents": 3000, "method": "CARD",
                      "expected_invoice_version": invoice["version"]},
                     BILLING), 201)
    res = api.void_invoice(invoice["id"], BILLING)
    validate_error(res, "ERR_INVOICE_HAS_PAYMENTS", expected_status=409)


def test_invoice_uncompleted_job_rejected(api):
    """PRD §3.4: "Issuing requires that the job's lifecycle_status be COMPLETED; an
    attempt to invoice a job that has not completed is rejected with
    ERR_JOB_NOT_COMPLETED."

    Design: Corner/validations/invoice_uncompleted_job_rejected
    """
    ctx = setup_booked_job(rooms=[("Rm", 100, "LIGHT")])
    res = api.issue_invoice(ctx["job"]["id"], BILLING)
    validate_error(res, "ERR_JOB_NOT_COMPLETED", expected_status=409)


# ─── corner: OCC on invoice payment ───────────────────────────

def test_stale_invoice_version_on_payment_rejected(api):
    """PRD §2.9: "If the invoice has been advanced since the client last read it —
    because an earlier payment, a void, or a settlement bumped its version — the
    payment reflects a stale view of the invoice and is rejected with
    ERR_STALE_INVOICE_VERSION (HTTP 412)."

    A first 2000 payment bumps version 1->2; a second payment still carrying the
    stale version 1 is rejected.

    Design: Corner/cross_cutting_complexity_layers/occ_stale_invoice_version_on_payment
    """
    ctx = setup_invoiced_job(rooms=[("Rm", 100, "LIGHT")])
    invoice = ctx["invoice"]
    stale_version = invoice["version"]
    validate_success(api.record_payment(invoice["id"],
                     {"amount_cents": 2000, "method": "CASH",
                      "expected_invoice_version": stale_version},
                     BILLING), 201)
    res = api.record_payment(invoice["id"],
                             {"amount_cents": 1000, "method": "CASH",
                              "expected_invoice_version": stale_version},
                             BILLING)
    validate_error(res, "ERR_STALE_INVOICE_VERSION", expected_status=412)
