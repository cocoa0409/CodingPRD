"""Filtered list reads and the audit trail (PRD §2.8, §3.9).
Each test translates exactly one corner-design endpoint instance.
"""
from test_helpers import (
    validate_success, validate_paginated,
    create_gl_account, create_vendor, capture_invoice, create_lined_invoice,
    code_invoice,
    setup_scheduled_payment,
    TEST_USERS,
)

MGR = TEST_USERS["manager_headers"]
CLERK = TEST_USERS["clerk_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


def test_list_invoices_filtered_by_vendor(api):
    """PRD §2.3: "The `meta` object of every list response carries `limit`, `offset`,
    `total_count`, and `has_more`, where `total_count` is the count of all matching
    resources before pagination".

    Design: Corner/endpoints/list_invoices_filtered_by_vendor
    """
    vendor = create_vendor(legal_name="Filt", payment_method="ACH")
    inv = capture_invoice(vendor["id"], invoice_number="FILT-1")
    resp = api.list_invoices(AUDITOR, params={"vendor_id": vendor["id"]})
    data, meta = validate_paginated(resp)
    ids = [row["id"] for row in data]
    # The vendor has exactly one invoice, so a vendor-scoped list must contain it.
    assert inv["id"] in ids, f"expected invoice {inv['id']} in {ids}"
    assert all(row["vendor_id"] == vendor["id"] for row in data)


def test_list_payments_filtered_by_invoice(api):
    """PRD §2.3: "The `meta` object of every list response carries `limit`, `offset`,
    `total_count`, and `has_more`, where `total_count` is the count of all matching
    resources before pagination".

    Design: Corner/endpoints/list_payments_filtered_by_invoice
    """
    vendor, invoice, batch, payment = setup_scheduled_payment(amount_cents=50000)
    resp = api.list_payments(AUDITOR, params={"invoice_id": invoice["id"]})
    data, meta = validate_paginated(resp)
    ids = [row["id"] for row in data]
    # The invoice has exactly one payment, so an invoice-scoped list must contain it.
    assert payment["id"] in ids, f"expected payment {payment['id']} in {ids}"


def test_list_invoice_audit_events_reverse_reachable(api):
    """PRD §3.9: "Every consequential transition on an invoice is recorded as an audit
    event linked to that invoice via `invoice_id`. Each event carries a system-assigned
    `event_type` label (for example `CODED`, ...)".

    Design: Corner/endpoints/list_invoice_audit_events_reverse_reachable
    """
    create_gl_account()
    vendor = create_vendor(legal_name="Aud", payment_method="ACH")
    inv = create_lined_invoice(vendor["id"], 1000, invoice_number="AUD-1")
    code_invoice(inv["id"])  # produces a CODED audit event
    resp = api.list_invoice_audit_events(inv["id"], AUDITOR)
    data, meta = validate_paginated(resp)
    assert len(data) >= 1, "expected at least one audit event after coding"
