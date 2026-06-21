"""Invoicing, payment application, voiding, the account-balance ledger, and the
annual tax statement.

Translates queue-A difficulty instances (transitive_cascade issue-ledger,
compensating_invariant void-conserves-balance) and queue-B corner instances
(invoice_total, tax_statement, payment->PAID, overpayment, empty-invoice,
void-with-partial-payment, OCC payment).
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    make_director_headers, make_billing_headers, ApiErrorId,
)
import test_helpers.fixtures as fx

DIRECTOR = make_director_headers()
BILLING = make_billing_headers()


def test_issue_invoice_freezes_total_and_syncs_ledger(api):
    """PRD §3.7: "tuition_cents is frozen as the sum of the family's ACTIVE
    enrollments' monthly_net_tuition_cents ... total_cents is set to tuition_cents
    plus late_fines_cents ... and the family's account_balance_cents is increased
    by total_cents to keep the ledger in sync."

    FULL_PAY base 120000 -> total 120000, balance 120000.

    Design: Difficulty/transitive_cascade/issue_invoice_ledger_balance_depth2
    """
    center, classroom, family, child, enrollment = fx.setup_single_active_enrollment(
        classroom_overrides={"base_monthly_tuition_cents": 120000})
    draft = fx.create_invoice(family["id"], "2026-03")
    resp = api.issue_invoice(draft["id"], BILLING)
    issued = validate_success(resp, 200)
    assert issued["total_cents"] == 120000
    fam = get_success_data(api.get_family(family["id"], DIRECTOR))
    assert fam["account_balance_cents"] == 120000


def test_issue_invoice_tuition_component_frozen(api):
    """PRD §3.7: "On issue, tuition_cents is frozen as the sum of the family's
    ACTIVE enrollments' monthly_net_tuition_cents".

    Design: Difficulty/transitive_cascade/issue_invoice_ledger_balance_depth2
    """
    center, classroom, family, child, enrollment = fx.setup_single_active_enrollment(
        classroom_overrides={"base_monthly_tuition_cents": 120000})
    draft = fx.create_invoice(family["id"], "2026-03")
    issued = get_success_data(api.issue_invoice(draft["id"], BILLING))
    assert issued["tuition_cents"] == 120000


def test_invoice_total_sums_tuition_and_late_fines(api):
    """PRD §3.7: "total_cents is set to tuition_cents plus late_fines_cents (an
    exact sum of already-rounded integer components)".
    PRD §3.7: "late_fines_cents is frozen as the sum of late_fine_cents across the
    family's CHECKED_OUT attendance records whose service_date falls in the billing
    month".

    net tuition 120000 + one 1500 late fine -> total 121500.

    Design: Corner/calculations/invoice_total_sums_tuition_and_late_fines
    """
    fx.set_clock("2026-03-02T16:00:00Z")
    center, classroom, family, child, enrollment = fx.setup_single_active_enrollment(
        center_overrides={"cacfp_tier": "TIER_I", "late_pickup_grace_minutes": 5,
                          "late_pickup_fee_per_block_cents": 1500,
                          "late_pickup_block_minutes": 15},
        classroom_overrides={"base_monthly_tuition_cents": 120000})
    att = fx.create_attendance(classroom, enrollment, "2026-03-02", "17:00")
    fx.set_clock("2026-03-02T17:06:00Z")
    fx.check_out(classroom, att)
    draft = fx.create_invoice(family["id"], "2026-03")
    issued = get_success_data(api.issue_invoice(draft["id"], BILLING))
    assert issued["tuition_cents"] == 120000
    assert issued["late_fines_cents"] == 1500
    assert issued["total_cents"] == 121500


def test_payment_drives_invoice_to_paid(api):
    """PRD §3.7: "When the cumulative amount_paid_cents reaches or exceeds
    total_cents, the invoice transitions from ISSUED to PAID".

    Design: Corner/state_machines/payment_drives_invoice_to_paid_bubble_up
    """
    center, classroom, family, child, enrollment, issued = fx.setup_issued_invoice(
        base_tuition_cents=120000)
    resp = api.create_payment(
        {"invoice_id": issued["id"], "amount_cents": 120000, "method": "CARD",
         "expected_invoice_version": issued["version"]}, BILLING)
    validate_success(resp, 201)
    inv = get_success_data(api.get_invoice(issued["id"], BILLING))
    assert inv["status"] == "PAID"
    assert inv["amount_paid_cents"] == 120000


def test_overpayment_rejected(api):
    """PRD §3.7: "A payment may not exceed the invoice's outstanding balance — that
    is, amount_cents may not be greater than total_cents minus the current
    amount_paid_cents — and an overpayment is rejected with ERR_OVERPAYMENT."

    Design: Corner/validations/overpayment_rejected
    """
    center, classroom, family, child, enrollment, issued = fx.setup_issued_invoice(
        base_tuition_cents=120000)
    resp = api.create_payment(
        {"invoice_id": issued["id"], "amount_cents": 120001, "method": "CARD",
         "expected_invoice_version": issued["version"]}, BILLING)
    validate_error(resp, ApiErrorId.ERR_OVERPAYMENT.value)


def test_empty_invoice_issue_rejected(api):
    """PRD §3.7: "A billing administrator issues a draft invoice, moving it from
    DRAFT to ISSUED, but only when the family has at least one ACTIVE enrollment or
    at least one late fine in the billing month — an invoice that would have neither
    is rejected with ERR_EMPTY_INVOICE."

    Design: Corner/validations/empty_invoice_issue_rejected
    """
    center = fx.create_center(cacfp_tier="TIER_I")
    family = fx.create_family(center["id"])
    draft = fx.create_invoice(family["id"], "2026-03")
    resp = api.issue_invoice(draft["id"], BILLING)
    validate_error(resp, ApiErrorId.ERR_EMPTY_INVOICE.value)


def test_void_issued_invoice_conserves_account_balance(api):
    """PRD §3.7: "on a successful void of an issued invoice the family's
    account_balance_cents is decreased by total_cents, compensating the debit
    recorded at issue time so the balance returns to its pre-issue value."

    issue debits +120000, void credits -120000 -> balance back to 0.

    Design: Difficulty/compensating_invariant/void_issued_invoice_conserves_account_balance
    """
    center, classroom, family, child, enrollment, issued = fx.setup_issued_invoice(
        base_tuition_cents=120000)
    resp = api.void_invoice(issued["id"], BILLING)
    data = validate_success(resp, 200)
    assert data["status"] == "VOID"
    fam = get_success_data(api.get_family(family["id"], DIRECTOR))
    assert fam["account_balance_cents"] == 0


def test_void_issued_invoice_transitions_to_void(api):
    """PRD §3.7: "A billing administrator may void an invoice from either DRAFT or
    ISSUED. ... Every void increments the invoice's version."

    Design: Difficulty/compensating_invariant/void_issued_invoice_conserves_account_balance
    """
    center, classroom, family, child, enrollment, issued = fx.setup_issued_invoice(
        base_tuition_cents=120000)
    resp = api.void_invoice(issued["id"], BILLING)
    data = validate_success(resp, 200)
    assert data["status"] == "VOID"
    assert data["version"] > issued["version"]


def test_void_issued_invoice_with_partial_payment_blocked(api):
    """PRD §3.7: "Voiding an ISSUED invoice requires that amount_paid_cents be
    exactly 0 — an issued invoice that has already received any payment cannot be
    voided and is rejected with ERR_INVOICE_HAS_PAYMENTS".

    Design: Corner/endpoints/void_issued_invoice_with_partial_payment_blocked
    """
    center, classroom, family, child, enrollment, issued = fx.setup_issued_invoice(
        base_tuition_cents=120000)
    fx.apply_payment(issued, 50000, method="CARD")
    resp = api.void_invoice(issued["id"], BILLING)
    validate_error(resp, ApiErrorId.ERR_INVOICE_HAS_PAYMENTS.value)


def test_tax_statement_cash_basis_sums_paid_invoices(api):
    """PRD §3.8: "Its total_paid_cents is the sum of amount_cents across all
    payments whose invoice belongs to this family, whose invoice is in PAID status,
    and whose invoice billing_month falls within the requested tax year."
    PRD §3.8: "child_count, the distinct number of the family's children who held
    an ACTIVE enrollment at any point during the tax year".

    two PAID 120000 invoices in 2026 -> total 240000, child_count 1.

    Design: Corner/calculations/tax_statement_cash_basis_sums_paid_invoices
    """
    center, classroom, family, child, enrollment = fx.setup_single_active_enrollment(
        classroom_overrides={"base_monthly_tuition_cents": 120000})
    for month in ("2026-01", "2026-02"):
        draft = fx.create_invoice(family["id"], month)
        issued = fx.issue_invoice(draft["id"])
        fx.apply_payment(issued, issued["total_cents"], method="ACH")
    resp = api.create_tax_statement(family["id"], {"tax_year": 2026}, BILLING)
    data = validate_success(resp, 201)
    assert data["total_paid_cents"] == 240000
    assert data["child_count"] == 1


def test_occ_payment_stale_invoice_version_rejected(api):
    """PRD §2.7: "A create-payment request must carry expected_invoice_version, a
    non-optional field holding the client's last observed version of the target
    Invoice. If that value does not equal the invoice's current version ... the
    payment is rejected with ERR_STALE_VERSION (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_payment_stale_invoice_version_rejected
    """
    center, classroom, family, child, enrollment, issued = fx.setup_issued_invoice(
        base_tuition_cents=120000)
    stale_version = issued["version"]
    fx.apply_payment(issued, 50000, method="CARD")  # advances invoice version
    resp = api.create_payment(
        {"invoice_id": issued["id"], "amount_cents": 50000, "method": "CARD",
         "expected_invoice_version": stale_version}, BILLING)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)
