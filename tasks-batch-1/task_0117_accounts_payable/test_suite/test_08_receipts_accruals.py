"""Goods receipts (posting, overlap, closed PO) and accruals (estimate/final,
period overlap) — PRD §3.2, §3.8. All translated instances are difficulty
instances and get >=2 tests each.
"""
from test_helpers import (
    validate_success, validate_error,
    create_gl_account, create_vendor, create_purchase_order, create_posted_receipt,
    create_lined_invoice, code_invoice, book_accrual,
    api_client,
    TEST_USERS,
)

MGR = TEST_USERS["manager_headers"]
CLERK = TEST_USERS["clerk_headers"]


# ---------------------------------------------------------------------------
# Difficulty: dual_variant_calc / accrual_estimate_vs_final_true_up_diverges
# ESTIMATE booked received=100000/matched=0 -> 100000; after invoice 100500 matches
# (matched=100500) FINAL -> max(0, 100000-100500)=0. (>=2 tests.)
# ---------------------------------------------------------------------------
def test_accrual_estimate_is_unbilled_receipt_gap_at_booking(api):
    """PRD §3.8: "The booked `estimated_cents` is the greater of 0 and the purchase
    order's `received_amount_cents` minus its `matched_amount_cents` — the unbilled
    receipt gap as of booking, never allowed to go negative."

    Design: Difficulty/dual_variant_calc/accrual_estimate_vs_final_true_up_diverges
    """
    create_gl_account()
    vendor = create_vendor(legal_name="Acme", payment_method="ACH")
    po = create_purchase_order(vendor["id"], ordered_amount_cents=100000)
    create_posted_receipt(po["id"], 100000)
    resp = api.create_accrual(
        {"po_id": po["id"], "period_label": "2026-05",
         "period_start": "2026-05-01", "period_end": "2026-05-31"}, MGR)
    data = validate_success(resp, 201)
    assert data["estimated_cents"] == 100000, f"expected 100000, got {data['estimated_cents']}"
    assert data["status"] == "BOOKED"


def test_accrual_final_recomputes_after_matching_diverges_from_estimate(api):
    """PRD §3.8: "Reversing an accrual performs the chronological true-up: it computes
    `final_cents` as the greater of 0 and the same difference — the purchase order's
    `received_amount_cents` minus its `matched_amount_cents` — but recomputed from those
    two fields as they stand at reversal time, then moves the accrual to `REVERSED`. The
    final figure diverges from the original estimate precisely when invoices matched
    against the PO between booking and reversal".

    Design: Difficulty/dual_variant_calc/accrual_estimate_vs_final_true_up_diverges
    """
    create_gl_account()
    vendor = create_vendor(legal_name="Acme", payment_method="ACH")
    po = create_purchase_order(vendor["id"], ordered_amount_cents=100000)
    create_posted_receipt(po["id"], 100000)
    accrual = book_accrual(po["id"])
    assert accrual["estimated_cents"] == 100000
    # An invoice of 100500 matches in tolerance, pushing matched to 100500.
    inv = create_lined_invoice(vendor["id"], 100500, po_id=po["id"], invoice_number="INV-ACC",
                               invoice_date="2026-05-10")
    matched = code_invoice(inv["id"])
    assert matched["status"] == "MATCHED"
    resp = api.reverse_accrual(accrual["id"], MGR)
    data = validate_success(resp, 200)
    assert data["final_cents"] == 0, f"expected 0, got {data['final_cents']}"
    assert data["status"] == "REVERSED"


# ---------------------------------------------------------------------------
# Difficulty: cross_entity_state_dependency / goods_receipt_post_blocked_by_closed_po
# PO ordered 100000, THREE_WAY invoice 100000 matches -> matched 100000 >= ordered ->
# CLOSED. A second DRAFT receipt then cannot post. (>=2 tests.)
# ---------------------------------------------------------------------------
def test_match_to_ordered_total_closes_po(api):
    """PRD §2.6: "it is `OPEN` until its `matched_amount_cents` reaches or exceeds its
    `ordered_amount_cents`, at which point it becomes `CLOSED`. Because the
    reconciliation is immediate, a match that pushes matched spend to the ordered total
    closes the PO in the same operation".

    Design: Difficulty/cross_entity_state_dependency/goods_receipt_post_blocked_by_closed_po
    """
    create_gl_account()
    vendor = create_vendor(legal_name="Acme", payment_method="ACH")
    po = create_purchase_order(vendor["id"], ordered_amount_cents=100000)
    create_posted_receipt(po["id"], 100000)
    inv = create_lined_invoice(vendor["id"], 100000, po_id=po["id"], invoice_number="INV-CLOSE",
                               invoice_date="2026-05-10")
    code_invoice(inv["id"])
    po_after = validate_success(api.get_purchase_order(po["id"], MGR), 200)
    assert po_after["status"] == "CLOSED"


def test_post_receipt_against_closed_po_rejected(api):
    """PRD §3.2: "A receipt may not be posted against a `CLOSED` purchase order; such an
    attempt is rejected with `ERR_PO_CLOSED`."

    Design: Difficulty/cross_entity_state_dependency/goods_receipt_post_blocked_by_closed_po
    """
    create_gl_account()
    vendor = create_vendor(legal_name="Acme", payment_method="ACH")
    po = create_purchase_order(vendor["id"], ordered_amount_cents=100000)
    create_posted_receipt(po["id"], 100000)
    inv = create_lined_invoice(vendor["id"], 100000, po_id=po["id"], invoice_number="INV-CLOSE2",
                               invoice_date="2026-05-10")
    code_invoice(inv["id"])  # closes the PO
    # A second DRAFT receipt (non-overlapping window) cannot post against the CLOSED PO.
    gr2 = validate_success(api.create_goods_receipt(
        {"po_id": po["id"], "received_amount_cents": 5000,
         "received_date": "2026-05-20", "coverage_days": 3}, CLERK), 201)
    resp = api.post_goods_receipt(gr2["id"], CLERK)
    validate_error(resp, "ERR_PO_CLOSED", 409)


# ---------------------------------------------------------------------------
# Difficulty: resource_temporal_overlap /
#   goods_receipt_half_open_window_overlap_rejected_adjacency_ok
# POSTED [2026-05-01, 2026-05-06); adjacent [2026-05-06, 2026-05-09) OK;
# overlapping [2026-05-03, 2026-05-08) rejected. (>=2 tests.)
# ---------------------------------------------------------------------------
def _po_with_first_receipt():
    create_gl_account()
    vendor = create_vendor(legal_name="Acme", payment_method="ACH")
    po = create_purchase_order(vendor["id"], ordered_amount_cents=1000000)
    create_posted_receipt(po["id"], 10000, received_date="2026-05-01", coverage_days=5)
    return po


def test_adjacent_receipt_window_posts_successfully(api):
    """PRD §3.2: "because the interval is half-open, mere adjacency — where one window's
    end instant equals the next window's start instant — is permitted and does not count
    as an overlap".

    Design: Difficulty/resource_temporal_overlap/goods_receipt_half_open_window_overlap_rejected_adjacency_ok
    """
    po = _po_with_first_receipt()  # [2026-05-01, 2026-05-06)
    gr_adj = validate_success(api.create_goods_receipt(
        {"po_id": po["id"], "received_amount_cents": 10000,
         "received_date": "2026-05-06", "coverage_days": 3}, CLERK), 201)
    resp = api.post_goods_receipt(gr_adj["id"], CLERK)
    data = validate_success(resp, 200)
    assert data["status"] == "POSTED"


def test_overlapping_receipt_window_rejected(api):
    """PRD §3.2: "Posting is also blocked when the new receipt's half-open coverage
    window would overlap the window of any receipt already POSTED on the same PO ... but
    any true overlap is rejected with `ERR_RECEIPT_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/goods_receipt_half_open_window_overlap_rejected_adjacency_ok
    """
    po = _po_with_first_receipt()  # POSTED [2026-05-01, 2026-05-06)
    gr_ovl = validate_success(api.create_goods_receipt(
        {"po_id": po["id"], "received_amount_cents": 10000,
         "received_date": "2026-05-03", "coverage_days": 5}, CLERK), 201)  # [05-03, 05-08)
    resp = api.post_goods_receipt(gr_ovl["id"], CLERK)
    validate_error(resp, "ERR_RECEIPT_WINDOW_OVERLAP", 409)


# ---------------------------------------------------------------------------
# Difficulty: resource_temporal_overlap /
#   accrual_closed_period_overlap_rejected_shared_endpoint_counts
# BOOKED [2026-05-01, 2026-05-31]; second [2026-05-31, 2026-06-30] shares 05-31 -> reject.
# (>=2 tests.)
# ---------------------------------------------------------------------------
def _po_with_booked_accrual():
    create_gl_account()
    vendor = create_vendor(legal_name="Acme", payment_method="ACH")
    po = create_purchase_order(vendor["id"], ordered_amount_cents=100000)
    book_accrual(po["id"], period_label="2026-05",
                 period_start="2026-05-01", period_end="2026-05-31")
    return po


def test_accrual_sharing_endpoint_date_rejected(api):
    """PRD §3.8: "an accrual may not be booked when its period interval overlaps that of
    any existing `BOOKED` accrual on the same PO; since both endpoints are inclusive,
    even sharing a single endpoint date counts as an overlap (no adjacency is
    permitted), and such an attempt is rejected with `ERR_ACCRUAL_PERIOD_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/accrual_closed_period_overlap_rejected_shared_endpoint_counts
    """
    po = _po_with_booked_accrual()  # [2026-05-01, 2026-05-31]
    resp = api.create_accrual(
        {"po_id": po["id"], "period_label": "2026-06",
         "period_start": "2026-05-31", "period_end": "2026-06-30"}, MGR)
    validate_error(resp, "ERR_ACCRUAL_PERIOD_OVERLAP", 409)


def test_accrual_non_overlapping_period_books_successfully(api):
    """PRD §3.8: "the period occupies the closed interval from start to end inclusive
    and the end must be on or after the start. Booking computes the estimate and creates
    the accrual in `BOOKED`".

    Design: Difficulty/resource_temporal_overlap/accrual_closed_period_overlap_rejected_shared_endpoint_counts
    """
    # Boundary complement: a period starting strictly after the prior end (06-01, not
    # the shared 05-31) does not overlap a closed interval and books cleanly.
    po = _po_with_booked_accrual()  # [2026-05-01, 2026-05-31]
    resp = api.create_accrual(
        {"po_id": po["id"], "period_label": "2026-06",
         "period_start": "2026-06-01", "period_end": "2026-06-30"}, MGR)
    data = validate_success(resp, 201)
    assert data["status"] == "BOOKED"
