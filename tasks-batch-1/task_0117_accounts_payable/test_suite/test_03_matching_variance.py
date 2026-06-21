"""Match variance: dual-basis interpretation, tolerance breach, revision loop
(PRD §3.4). Difficulty instances get >=2 tests each.
"""
from test_helpers import (
    validate_success,
    create_gl_account, create_vendor, create_purchase_order, create_posted_receipt,
    create_lined_invoice, code_invoice, get_first_match_exception,
    setup_breach_exception,
    api_client,
    TEST_USERS,
)

MGR = TEST_USERS["manager_headers"]
CLERK = TEST_USERS["clerk_headers"]


# ---------------------------------------------------------------------------
# Difficulty: dual_variant_calc / match_variance_two_way_vs_three_way_basis_diverges
# Same invoice amount (90000) vs same ordered PO (100000) -> -10000 TWO_WAY,
# 0 THREE_WAY (received 90000). (>=2 tests on this instance.)
# ---------------------------------------------------------------------------
def test_two_way_variance_measured_against_ordered(api):
    """PRD §3.4: "For a `TWO_WAY` invoice the variance is the invoice's
    `total_amount_cents` minus the purchase order's `ordered_amount_cents` — billed
    against ordered."
    PRD §3.3: "it is ... `TWO_WAY` if it has none." [POSTED goods receipts]

    Design: Difficulty/dual_variant_calc/match_variance_two_way_vs_three_way_basis_diverges
    """
    create_gl_account()
    vendor = create_vendor(legal_name="Acme", payment_method="ACH")
    po = create_purchase_order(vendor["id"], ordered_amount_cents=100000)
    inv = create_lined_invoice(vendor["id"], 90000, po_id=po["id"], invoice_number="INV-2W",
                               invoice_date="2026-05-10")
    resp = api.code_invoice(inv["id"], CLERK)
    data = validate_success(resp, 200)
    assert data["match_type"] == "TWO_WAY"
    assert data["variance_cents"] == -10000, f"expected -10000, got {data['variance_cents']}"
    # |−10000| > tolerance max(1000, round(100000*0.02)=2000) -> breach -> held in CODING_REVIEW.
    assert data["status"] == "CODING_REVIEW"


def test_three_way_variance_measured_against_received(api):
    """PRD §3.4: "For a `THREE_WAY` invoice the variance is the invoice's
    `total_amount_cents` minus the purchase order's `received_amount_cents` — billed
    against what was actually received".
    PRD §3.3: "it is `THREE_WAY` if that PO has at least one POSTED goods receipt at
    capture time".

    Design: Difficulty/dual_variant_calc/match_variance_two_way_vs_three_way_basis_diverges
    """
    create_gl_account()
    vendor = create_vendor(legal_name="Acme", payment_method="ACH")
    po = create_purchase_order(vendor["id"], ordered_amount_cents=100000)
    create_posted_receipt(po["id"], 90000)
    inv = create_lined_invoice(vendor["id"], 90000, po_id=po["id"], invoice_number="INV-3W",
                               invoice_date="2026-05-10")
    resp = api.code_invoice(inv["id"], CLERK)
    data = validate_success(resp, 200)
    assert data["match_type"] == "THREE_WAY"
    assert data["variance_cents"] == 0, f"expected 0, got {data['variance_cents']}"
    assert data["status"] == "MATCHED"


# ---------------------------------------------------------------------------
# Difficulty: combinatorial_formula / match_variance_tolerance_nonlinear_mode_a
# Invoice 102100 vs PO ordered/received 100000 -> variance 2100; tolerance
# max(1000, round(100000*0.02)=2000)=2000; 2100 > 2000 -> breach. (>=2 tests.)
# ---------------------------------------------------------------------------
def test_tolerance_breach_when_variance_strictly_above_tolerance(api):
    """PRD §3.4: "The tolerance is computed as the larger of an absolute floor of 1000
    cents and the purchase order's `ordered_amount_cents` multiplied by a percentage
    tolerance of 0.02, with that percentage product rounded half-up to the nearest cent."
    PRD §3.4: "The variance breaches tolerance only when its absolute magnitude is
    strictly greater than the tolerance".

    Design: Difficulty/combinatorial_formula/match_variance_tolerance_nonlinear_mode_a
    """
    create_gl_account()
    vendor = create_vendor(legal_name="Acme", payment_method="ACH")
    po = create_purchase_order(vendor["id"], ordered_amount_cents=100000)
    create_posted_receipt(po["id"], 100000)
    inv = create_lined_invoice(vendor["id"], 102100, po_id=po["id"], invoice_number="INV-TOL",
                               invoice_date="2026-05-10")
    resp = api.code_invoice(inv["id"], CLERK)
    data = validate_success(resp, 200)
    assert data["variance_cents"] == 2100, f"expected 2100, got {data['variance_cents']}"
    assert data["status"] == "CODING_REVIEW"


def test_tolerance_breach_creates_qty_variance_exception(api):
    """PRD §3.4: "When the variance breaches tolerance, instead of advancing to
    `MATCHED` the invoice is held in `CODING_REVIEW` and a match exception is created
    in `PENDING`: its `reason` is `PRICE_VARIANCE` for a `TWO_WAY` breach and
    `QTY_VARIANCE` for a `THREE_WAY` breach, and its `variance_cents` is copied from
    the invoice's variance at creation."

    Design: Difficulty/combinatorial_formula/match_variance_tolerance_nonlinear_mode_a
    """
    create_gl_account()
    vendor = create_vendor(legal_name="Acme", payment_method="ACH")
    po = create_purchase_order(vendor["id"], ordered_amount_cents=100000)
    create_posted_receipt(po["id"], 100000)
    inv = create_lined_invoice(vendor["id"], 102100, po_id=po["id"], invoice_number="INV-TOL2",
                               invoice_date="2026-05-10")
    code_invoice(inv["id"])
    exc = get_first_match_exception(inv["id"])
    assert exc["reason"] == "QTY_VARIANCE"
    assert exc["resolution"] == "PENDING"
    assert exc["variance_cents"] == 2100


# ---------------------------------------------------------------------------
# Difficulty: non_linear_state_machine / invoice_coding_review_revision_cycle
# CAPTURED -> (breach) CODING_REVIEW -> (exception RESOLVED) -> re-code -> MATCHED.
# THREE_WAY, ordered 100000, received 80000, invoice 100000 -> variance 20000. (>=2 tests.)
# ---------------------------------------------------------------------------
def test_breach_holds_invoice_in_coding_review_with_pending_exception(api):
    """PRD §3.4: "When the variance breaches tolerance, instead of advancing to
    `MATCHED` the invoice is held in `CODING_REVIEW` and a match exception is created
    in `PENDING`".

    Design: Difficulty/non_linear_state_machine/invoice_coding_review_revision_cycle
    """
    create_gl_account()
    vendor = create_vendor(legal_name="Acme", payment_method="ACH")
    po = create_purchase_order(vendor["id"], ordered_amount_cents=100000)
    create_posted_receipt(po["id"], 80000)
    inv = create_lined_invoice(vendor["id"], 100000, po_id=po["id"], invoice_number="INV-CYC",
                               invoice_date="2026-05-10")
    resp = api.code_invoice(inv["id"], CLERK)
    data = validate_success(resp, 200)
    assert data["status"] == "CODING_REVIEW"
    exc = get_first_match_exception(inv["id"])
    assert exc["reason"] == "QTY_VARIANCE"
    assert exc["resolution"] == "PENDING"


def test_resolved_exception_lets_recode_reach_matched(api):
    """PRD §3.4: "Once every exception on the invoice is non-pending, the clerk re-runs
    the match, which recomputes the match type and variance, records `coded_by`,
    advances the invoice to `MATCHED`, recomputes the PO's matched amount (possibly
    closing the PO), and appends a `CODED` event — closing the revision loop."
    PRD §3.4: "**Resolving** the exception accepts the variance as-is, moves the
    resolution to `RESOLVED`".

    Design: Difficulty/non_linear_state_machine/invoice_coding_review_revision_cycle
    """
    create_gl_account()
    vendor = create_vendor(legal_name="Acme", payment_method="ACH")
    po = create_purchase_order(vendor["id"], ordered_amount_cents=100000)
    create_posted_receipt(po["id"], 80000)
    inv = create_lined_invoice(vendor["id"], 100000, po_id=po["id"], invoice_number="INV-CYC2",
                               invoice_date="2026-05-10")
    code_invoice(inv["id"])
    exc = get_first_match_exception(inv["id"])
    validate_success(api.resolve_match_exception(exc["id"], CLERK), 200)
    resp = api.code_invoice(inv["id"], CLERK)
    data = validate_success(resp, 200)
    assert data["status"] == "MATCHED"
    exc_after = validate_success(api.get_match_exception(exc["id"], CLERK), 200)
    assert exc_after["resolution"] == "RESOLVED"


# ---------------------------------------------------------------------------
# Corner: cross_cutting_layers / derived_po_matched_amount_recomputed_on_match
# ---------------------------------------------------------------------------
def test_po_matched_amount_recomputed_on_match(api):
    """PRD §2.6: "A purchase order's `matched_amount_cents` is the sum of
    `total_amount_cents` over that PO's invoices whose status is one of `MATCHED`,
    `APPROVED`, `SCHEDULED`, or `PAID`, recomputed on every invoice match".
    PRD §2.6: "it is `OPEN` until its `matched_amount_cents` reaches or exceeds its
    `ordered_amount_cents`, at which point it becomes `CLOSED`."

    Design: Corner/cross_cutting_layers/derived_po_matched_amount_recomputed_on_match
    """
    create_gl_account()
    vendor = create_vendor(legal_name="Der", payment_method="ACH")
    po = create_purchase_order(vendor["id"], ordered_amount_cents=200000)
    create_posted_receipt(po["id"], 100000)
    inv = create_lined_invoice(vendor["id"], 100000, po_id=po["id"], invoice_number="DER-1",
                               invoice_date="2026-05-10")
    data = validate_success(api.code_invoice(inv["id"], CLERK), 200)
    assert data["status"] == "MATCHED"
    po_after = validate_success(api.get_purchase_order(po["id"], MGR), 200)
    assert po_after["matched_amount_cents"] == 100000
    assert po_after["status"] == "OPEN"
