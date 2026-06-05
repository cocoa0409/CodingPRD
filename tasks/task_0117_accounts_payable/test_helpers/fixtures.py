"""Composite setup helpers (PRD §3 workflows).

These encapsulate the multi-step preambles the test claims share so each test can
focus on its trigger + assertions. Setup calls use get_success_data() (lenient)
so a broken precondition surfaces as a clear "Setup step failed" message.

The database is empty at the start of every test (the runner restarts the server
before each test), so every helper builds its preconditions from scratch.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_manager_headers,
    make_clerk_headers,
    make_approver_headers,
)
from . import factories as f

MGR = TEST_USERS["manager_headers"]
CLERK = TEST_USERS["clerk_headers"]
APPROVER = TEST_USERS["approver_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


# ---------------------------------------------------------------------------
# Tier 1 — master data
# ---------------------------------------------------------------------------
def create_gl_account(code="5000", name="COGS", is_postable=True, headers=MGR) -> dict:
    return get_success_data(api_client.create_gl_account(
        f.create_gl_account_payload(code=code, name=name, is_postable=is_postable), headers))


def create_vendor(headers=MGR, **overrides) -> dict:
    return get_success_data(api_client.create_vendor(
        f.create_vendor_payload(**overrides), headers))


def create_purchase_order(vendor_id, headers=MGR, **overrides) -> dict:
    return get_success_data(api_client.create_purchase_order(
        f.create_purchase_order_payload(vendor_id, **overrides), headers))


def create_approval_route(min_amount_cents=0, max_amount_cents=1_000_000_000,
                          required_levels=1, headers=MGR) -> dict:
    return get_success_data(api_client.create_approval_route(
        f.create_approval_route_payload(
            min_amount_cents=min_amount_cents,
            max_amount_cents=max_amount_cents,
            required_levels=required_levels), headers))


def setup_master_data(gl_code="5000", **vendor_overrides):
    """A postable GL account + an ACTIVE vendor. Returns (gl, vendor)."""
    gl = create_gl_account(code=gl_code)
    vendor = create_vendor(**vendor_overrides)
    return gl, vendor


# ---------------------------------------------------------------------------
# Tier 2 — receiving against a PO
# ---------------------------------------------------------------------------
def create_posted_receipt(po_id, received_amount_cents, received_date="2026-05-01",
                          coverage_days=5, headers=CLERK) -> dict:
    """Create a DRAFT receipt and POST it, so it counts toward matching."""
    gr = get_success_data(api_client.create_goods_receipt(
        f.create_goods_receipt_payload(
            po_id, received_amount_cents=received_amount_cents,
            received_date=received_date, coverage_days=coverage_days), headers))
    posted = get_success_data(api_client.post_goods_receipt(gr["id"], headers))
    return posted


def setup_po_with_receipt(ordered_amount_cents=100000, received_amount_cents=100000,
                          gl_code="5000"):
    """GL + vendor + PO + one POSTED receipt (THREE_WAY ready).
    Returns (vendor, po, receipt)."""
    create_gl_account(code=gl_code)
    vendor = create_vendor()
    po = create_purchase_order(vendor["id"], gl_account_code=gl_code,
                               ordered_amount_cents=ordered_amount_cents)
    receipt = create_posted_receipt(po["id"], received_amount_cents)
    return vendor, po, receipt


# ---------------------------------------------------------------------------
# Tier 3 — invoice lifecycle shortcuts
# ---------------------------------------------------------------------------
def capture_invoice(vendor_id, invoice_number="INV-1", invoice_date="2026-05-01",
                    po_id=None, ocr_confidence=None, headers=CLERK) -> dict:
    payload = f.create_invoice_payload(vendor_id, invoice_number=invoice_number,
                                       invoice_date=invoice_date)
    if po_id is not None:
        payload["po_id"] = po_id
    if ocr_confidence is not None:
        payload["ocr_confidence"] = ocr_confidence
    return get_success_data(api_client.create_invoice(payload, headers))


def add_line(invoice_id, amount_cents, gl_account_code="5000", description="line",
             headers=CLERK) -> dict:
    return get_success_data(api_client.add_invoice_line(
        invoice_id, f.create_invoice_line_payload(
            gl_account_code=gl_account_code, amount_cents=amount_cents,
            description=description), headers))


def create_lined_invoice(vendor_id, amount_cents, invoice_number="INV-1",
                         invoice_date="2026-05-01", po_id=None, gl_account_code="5000",
                         clerk_headers=CLERK) -> dict:
    """Capture an invoice and add a single line of amount_cents. Returns the invoice
    (re-fetched so total_amount_cents reflects the line)."""
    inv = capture_invoice(vendor_id, invoice_number=invoice_number,
                          invoice_date=invoice_date, po_id=po_id, headers=clerk_headers)
    add_line(inv["id"], amount_cents, gl_account_code=gl_account_code,
             headers=clerk_headers)
    return get_success_data(api_client.get_invoice(inv["id"], clerk_headers))


def code_invoice(invoice_id, headers=CLERK) -> dict:
    return get_success_data(api_client.code_invoice(invoice_id, headers))


def get_first_match_exception(invoice_id, headers=CLERK) -> dict:
    data, _meta = _list(api_client.list_invoice_match_exceptions(invoice_id, headers))
    assert data, f"expected a match exception on invoice {invoice_id}"
    return data[0]


def _list(response):
    """Lenient list reader for setup: returns (data_list, meta)."""
    body = get_success_data(response)
    # get_success_data returns the data payload (the list itself for array responses)
    return body, None


def setup_breach_exception(ordered_amount_cents=100000, invoice_amount_cents=120000,
                           received_amount_cents=None, two_way=True):
    """Create an invoice whose coding breaches tolerance, producing a PENDING
    MatchException. Returns (vendor, po, invoice, exception).

    two_way=True -> TWO_WAY breach (no posted receipt; PRICE_VARIANCE).
    two_way=False -> THREE_WAY breach (posted receipt; QTY_VARIANCE)."""
    create_gl_account()
    vendor = create_vendor()
    po = create_purchase_order(vendor["id"], ordered_amount_cents=ordered_amount_cents)
    if not two_way:
        rcv = received_amount_cents if received_amount_cents is not None else ordered_amount_cents
        create_posted_receipt(po["id"], rcv)
    inv = create_lined_invoice(vendor["id"], invoice_amount_cents, po_id=po["id"])
    code_invoice(inv["id"])
    exc = get_first_match_exception(inv["id"])
    return vendor, po, inv, exc


# ---------------------------------------------------------------------------
# Tier 3b — invoice through APPROVED
# ---------------------------------------------------------------------------
def setup_approved_non_po_invoice(amount_cents=50000, vendor_overrides=None,
                                  required_levels=1, route_max=1_000_000_000,
                                  clerk_id=None, approver_id=None,
                                  invoice_number="INV-1", invoice_date="2026-05-01"):
    """GL + vendor + 1-tier route + a non-PO invoice coded, submitted, and fully
    approved. Returns (vendor, invoice). Optional clerk_id/approver_id thread a
    specific X-User-ID for segregation-of-duties scenarios."""
    vendor_overrides = vendor_overrides or {}
    create_gl_account()
    vendor = create_vendor(**vendor_overrides)
    create_approval_route(min_amount_cents=0, max_amount_cents=route_max,
                          required_levels=required_levels)
    clerk = make_clerk_headers(clerk_id) if clerk_id else CLERK
    approver = make_approver_headers(approver_id) if approver_id else APPROVER

    inv = create_lined_invoice(vendor["id"], amount_cents, invoice_number=invoice_number,
                               invoice_date=invoice_date, clerk_headers=clerk)
    code_invoice(inv["id"], headers=clerk)
    get_success_data(api_client.submit_invoice_for_approval(inv["id"], clerk))
    # Approve each level sequentially (lowest pending first).
    for _ in range(required_levels):
        steps, _m = _list(api_client.list_invoice_approval_steps(inv["id"], MGR))
        pending = [s for s in steps if s["status"] == "PENDING"]
        pending.sort(key=lambda s: s["level"])
        get_success_data(api_client.approve_step(pending[0]["id"], approver))
    invoice = get_success_data(api_client.get_invoice(inv["id"], MGR))
    return vendor, invoice


def setup_approved_three_way_invoice(ordered_amount_cents=200000,
                                     received_amount_cents=100000,
                                     invoice_amount_cents=100000):
    """GL + vendor + 1-tier route + PO + POSTED receipt + a THREE_WAY invoice coded
    in tolerance, submitted, and approved. Returns (vendor, po, invoice)."""
    create_gl_account()
    vendor = create_vendor()
    create_approval_route()
    po = create_purchase_order(vendor["id"], ordered_amount_cents=ordered_amount_cents)
    create_posted_receipt(po["id"], received_amount_cents)
    inv = create_lined_invoice(vendor["id"], invoice_amount_cents, po_id=po["id"],
                               invoice_number="INV-3W")
    code_invoice(inv["id"])
    get_success_data(api_client.submit_invoice_for_approval(inv["id"], CLERK))
    steps, _m = _list(api_client.list_invoice_approval_steps(inv["id"], MGR))
    get_success_data(api_client.approve_step(steps[0]["id"], APPROVER))
    invoice = get_success_data(api_client.get_invoice(inv["id"], MGR))
    po = get_success_data(api_client.get_purchase_order(po["id"], MGR))
    return vendor, po, invoice


# ---------------------------------------------------------------------------
# Tier 4 — payment batch shortcuts
# ---------------------------------------------------------------------------
def open_batch(payment_method="ACH", run_date="2026-05-10", headers=MGR) -> dict:
    return get_success_data(api_client.create_payment_batch(
        f.create_payment_batch_payload(payment_method=payment_method, run_date=run_date),
        headers))


def add_payment(batch_id, invoice_id, headers=MGR) -> dict:
    return get_success_data(api_client.add_payment(
        batch_id, f.add_payment_payload(invoice_id), headers))


def current_batch_version(batch_id, headers=MGR) -> int:
    return get_success_data(api_client.get_payment_batch(batch_id, headers))["version"]


def release_batch(batch_id, expected_version=None, headers=MGR) -> dict:
    if expected_version is None:
        expected_version = current_batch_version(batch_id, headers)
    return get_success_data(api_client.release_batch(
        batch_id, f.release_batch_payload(expected_version), headers))


def setup_scheduled_payment(amount_cents=50000, payment_method="ACH",
                            run_date="2026-05-10", vendor_overrides=None,
                            clerk_id=None, approver_id=None, manager_id=None):
    """An approved non-PO invoice added to a BUILDING batch (one Payment, invoice
    SCHEDULED). Returns (vendor, invoice, batch, payment)."""
    mgr = make_manager_headers(manager_id) if manager_id else MGR
    vendor, invoice = setup_approved_non_po_invoice(
        amount_cents=amount_cents, vendor_overrides=vendor_overrides,
        clerk_id=clerk_id, approver_id=approver_id)
    batch = open_batch(payment_method=payment_method, run_date=run_date, headers=mgr)
    payment = add_payment(batch["id"], invoice["id"], headers=mgr)
    return vendor, invoice, batch, payment


def setup_released_batch(amount_cents=50000, run_date="2026-05-10",
                         vendor_overrides=None):
    """An approved non-PO invoice scheduled and the batch RELEASED (invoice PAID).
    Releaser is a distinct operator so segregation of duties passes.
    Returns (vendor, invoice, batch, payment)."""
    vendor, invoice, batch, payment = setup_scheduled_payment(
        amount_cents=amount_cents, run_date=run_date, vendor_overrides=vendor_overrides)
    release_batch(batch["id"])
    batch = get_success_data(api_client.get_payment_batch(batch["id"], MGR))
    payment = get_success_data(api_client.get_payment(payment["id"], MGR))
    return vendor, invoice, batch, payment


def setup_settled_batch(amount_cents=50000, run_date="2026-06-30",
                        vendor_overrides=None):
    """An approved non-PO invoice paid in a RELEASED+SETTLED batch.
    Returns (vendor, invoice, batch, payment)."""
    vendor, invoice, batch, payment = setup_released_batch(
        amount_cents=amount_cents, run_date=run_date, vendor_overrides=vendor_overrides)
    get_success_data(api_client.settle_batch(batch["id"], MGR))
    batch = get_success_data(api_client.get_payment_batch(batch["id"], MGR))
    payment = get_success_data(api_client.get_payment(payment["id"], MGR))
    return vendor, invoice, batch, payment


# ---------------------------------------------------------------------------
# Tier 5 — accruals
# ---------------------------------------------------------------------------
def book_accrual(po_id, period_label="2026-05", period_start="2026-05-01",
                 period_end="2026-05-31", headers=MGR) -> dict:
    return get_success_data(api_client.create_accrual(
        f.create_accrual_payload(po_id, period_label=period_label,
                                 period_start=period_start, period_end=period_end),
        headers))
