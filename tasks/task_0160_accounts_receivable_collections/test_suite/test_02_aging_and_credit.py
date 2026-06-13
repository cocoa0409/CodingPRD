"""Aging classification and credit-posture threshold claims.

Queue A (Difficulty): dual-variant aging basis, aging 30-day boundary, credit
exposure==limit HOLD boundary. Queue B (Corner): WATCH at 80% threshold.
"""
from test_helpers import (
    validate_success,
    validate_error,
    set_clock,
    create_customer,
    create_invoice,
    create_invoice_payload,
)


def test_aging_bucket_due_date_basis_37_days_is_b31_60(api, ar_manager_headers, ar_clerk_headers):
    """PRD §3.2: "thirty-one through sixty days inclusive is `B31_60`".
    PRD §3.2: "For dunning and all credit decisions, the **due-date basis** is
    used: the reference date is the invoice's `due_date`."

    The invoice is issued 2026-01-15 but due 2026-03-25; at clock 2026-05-01 the
    due-date basis is 37 days overdue (B31_60) — distinct from any invoice-date
    reckoning. GET /ar/invoices/{id} returns the due-date-basis bucket.

    Design: Difficulty/dual_variant_calc/aging_bucket_due_vs_invoice_date_basis_diverge
    """
    set_clock("2026-05-01T00:00:00Z")
    customer = create_customer(name="C2")
    invoice = create_invoice(
        customer["id"],
        face_amount_cents=50_000,
        invoice_date="2026-01-15T00:00:00Z",
        due_date="2026-03-25T00:00:00Z",
    )
    fetched = validate_success(api.get_invoice(invoice["id"], ar_manager_headers), 200)
    assert fetched["aging_bucket"] == "B31_60", (
        f"due-date basis: 37 days overdue is B31_60, got {fetched['aging_bucket']}"
    )


def test_aging_bucket_due_date_basis_uses_due_not_invoice_date(api, ar_manager_headers, ar_clerk_headers):
    """PRD §3.2: "Unless a workflow explicitly names the invoice-date basis, the
    due-date basis applies."
    PRD §3.2: "ninety-one or more days overdue is `B91_PLUS`."

    An invoice 106 days past its invoice_date but only 37 past its due_date is
    classified by the due-date basis on read; if the reader wrongly used the
    invoice_date it would land in B91_PLUS, so this pins the basis selection.

    Design: Difficulty/dual_variant_calc/aging_bucket_due_vs_invoice_date_basis_diverge
    """
    set_clock("2026-05-01T00:00:00Z")
    customer = create_customer(name="C2b")
    invoice = create_invoice(
        customer["id"],
        face_amount_cents=50_000,
        invoice_date="2026-01-15T00:00:00Z",
        due_date="2026-03-25T00:00:00Z",
    )
    fetched = validate_success(api.get_invoice(invoice["id"], ar_manager_headers), 200)
    assert fetched["aging_bucket"] == "B31_60", (
        "read uses due-date basis (37 days), not invoice-date basis (106 days)"
    )


def test_aging_bucket_exact_30_days_is_b1_30(api, ar_manager_headers, ar_clerk_headers):
    """PRD §3.2: "The upper edge of each band is inclusive: exactly thirty days
    overdue is `B1_30`, and thirty-one days is `B31_60`."

    Design: Difficulty/boundary_precision_check/aging_bucket_exact_30_days_inclusive_boundary
    """
    customer = create_customer(name="AG")
    invoice = create_invoice(
        customer["id"],
        face_amount_cents=50_000,
        invoice_date="2026-02-01T00:00:00Z",
        due_date="2026-03-02T00:00:00Z",
    )
    set_clock("2026-04-01T00:00:00Z")  # exactly due + 30 days
    fetched = validate_success(api.get_invoice(invoice["id"], ar_manager_headers), 200)
    assert fetched["aging_bucket"] == "B1_30", (
        "30 days overdue is the inclusive top of B1_30"
    )


def test_aging_bucket_31_days_crosses_to_b31_60(api, ar_manager_headers, ar_clerk_headers):
    """PRD §3.2: "The upper edge of each band is inclusive: exactly thirty days
    overdue is `B1_30`, and thirty-one days is `B31_60`."

    The boundary's far side: one more day pushes the same invoice past the
    inclusive top of B1_30 into B31_60.

    Design: Difficulty/boundary_precision_check/aging_bucket_exact_30_days_inclusive_boundary
    """
    customer = create_customer(name="AG31")
    invoice = create_invoice(
        customer["id"],
        face_amount_cents=50_000,
        invoice_date="2026-02-01T00:00:00Z",
        due_date="2026-03-02T00:00:00Z",
    )
    set_clock("2026-04-02T00:00:00Z")  # due + 31 days
    fetched = validate_success(api.get_invoice(invoice["id"], ar_manager_headers), 200)
    assert fetched["aging_bucket"] == "B31_60", "31 days overdue is B31_60"


def test_credit_status_exposure_equals_limit_triggers_hold(api, ar_manager_headers, ar_clerk_headers):
    """PRD §2.7: "if `exposure_cents` is greater than or equal to
    `credit_limit_cents`, the status is `HOLD` — note the boundary is inclusive,
    so exposure exactly equal to the limit yields `HOLD`, not `WATCH`."

    Design: Difficulty/boundary_precision_check/credit_status_exposure_equals_limit_triggers_hold
    """
    customer = create_customer(name="CL", credit_limit_cents=100_000)
    create_invoice(
        customer["id"], face_amount_cents=100_000,
        invoice_date="2026-01-01T00:00:00Z", due_date="2026-02-01T00:00:00Z",
    )
    fetched = validate_success(api.get_customer(customer["id"], ar_manager_headers), 200)
    assert fetched["exposure_cents"] == 100_000
    assert fetched["credit_status"] == "HOLD", "exposure >= limit yields HOLD, not WATCH"


def test_credit_hold_at_limit_blocks_next_invoice(api, ar_manager_headers, ar_clerk_headers):
    """PRD §3.1: "Creation runs the credit gate of §2.7: if the customer is on
    `HOLD`, the invoice is refused with `ERR_CREDIT_HOLD`."
    PRD §2.7: "if `exposure_cents` is greater than or equal to
    `credit_limit_cents`, the status is `HOLD`".

    Once exposure equals the limit (HOLD), a second invoice is rejected.

    Design: Difficulty/boundary_precision_check/credit_status_exposure_equals_limit_triggers_hold
    """
    customer = create_customer(name="CL2", credit_limit_cents=100_000)
    create_invoice(
        customer["id"], face_amount_cents=100_000,
        invoice_date="2026-01-01T00:00:00Z", due_date="2026-02-01T00:00:00Z",
    )
    res = api.create_invoice(
        create_invoice_payload(
            customer["id"], face_amount_cents=1,
            invoice_date="2026-01-01T00:00:00Z", due_date="2026-02-01T00:00:00Z",
        ),
        ar_clerk_headers,
    )
    validate_error(res, "ERR_CREDIT_HOLD")


def test_credit_status_watch_at_80pct_threshold(api, ar_manager_headers, ar_clerk_headers):
    """PRD §2.7: "if `exposure_cents` is greater than or equal to eighty percent
    of `credit_limit_cents` (that watch threshold being computed as eighty
    percent of the limit, rounded half up to whole cents), the status is
    `WATCH`."

    Design: Corner/calculations/credit_status_watch_at_80pct_threshold
    """
    customer = create_customer(name="WT", credit_limit_cents=100_000)
    create_invoice(
        customer["id"], face_amount_cents=80_000,
        invoice_date="2026-01-01T00:00:00Z", due_date="2026-02-01T00:00:00Z",
    )
    fetched = validate_success(api.get_customer(customer["id"], ar_manager_headers), 200)
    assert fetched["credit_status"] == "WATCH", (
        "exposure 80000 == 80% of 100000 limit yields WATCH"
    )
