"""Tiered approval: tier selection, bubble-up, ordering, reject cascade (PRD §3.5).
The reject-cascade difficulty instance gets >=2 tests.
"""
from test_helpers import (
    validate_success, validate_error,
    create_gl_account, create_vendor, create_purchase_order, create_posted_receipt,
    create_approval_route, create_lined_invoice, code_invoice,
    api_client,
    TEST_USERS,
    make_approver_headers,
)

MGR = TEST_USERS["manager_headers"]
CLERK = TEST_USERS["clerk_headers"]
APPROVER = TEST_USERS["approver_headers"]


def _steps(invoice_id):
    return validate_success(api_client.list_invoice_approval_steps(invoice_id, MGR), 200)


# ---------------------------------------------------------------------------
# Corner: calculations / approval_tier_single_level_selection
# ---------------------------------------------------------------------------
def test_approval_tier_single_level_selection(api):
    """PRD §3.5: "The tier is the single approval route whose half-open cent interval
    contains the invoice's `total_amount_cents` — that is, the route whose lower bound
    is at or below the total while the total is strictly below the route's upper bound."
    PRD §3.5: "When the matching tier requires a single level, exactly one step is created".

    Design: Corner/calculations/approval_tier_single_level_selection
    """
    create_gl_account()
    vendor = create_vendor(legal_name="Tier", payment_method="ACH")
    create_approval_route(min_amount_cents=0, max_amount_cents=50000, required_levels=1)
    create_approval_route(min_amount_cents=50000, max_amount_cents=1_000_000_000, required_levels=2)
    inv = create_lined_invoice(vendor["id"], 40000, invoice_number="TIER-1")
    code_invoice(inv["id"])
    resp = api.submit_invoice_for_approval(inv["id"], CLERK)
    data = validate_success(resp, 200)
    assert data["status"] == "PENDING_APPROVAL"
    steps = _steps(inv["id"])
    assert len(steps) == 1, f"expected exactly one step, got {len(steps)}"
    assert steps[0]["level"] == 1


# ---------------------------------------------------------------------------
# Corner: state_machines / final_approval_bubbles_invoice_to_approved
# ---------------------------------------------------------------------------
def test_final_approval_bubbles_invoice_to_approved(api):
    """PRD §3.5: "If the approved step is the highest level on the invoice, the invoice
    bubbles up from `PENDING_APPROVAL` to `APPROVED`: the operator who approved that
    final step is recorded into the invoice's `approved_by`, and an `APPROVED` audit
    event is appended."

    Design: Corner/state_machines/final_approval_bubbles_invoice_to_approved
    """
    create_gl_account()
    vendor = create_vendor(legal_name="Bub", payment_method="ACH")
    create_approval_route(min_amount_cents=0, max_amount_cents=1_000_000_000, required_levels=1)
    inv = create_lined_invoice(vendor["id"], 50000, invoice_number="BUB-1")
    code_invoice(inv["id"])
    validate_success(api.submit_invoice_for_approval(inv["id"], CLERK), 200)
    step = _steps(inv["id"])[0]
    approver = make_approver_headers("APV1")
    validate_success(api.approve_step(step["id"], approver), 200)
    inv_after = validate_success(api.get_invoice(inv["id"], MGR), 200)
    assert inv_after["status"] == "APPROVED"
    assert inv_after["approved_by"] == "APV1"


# ---------------------------------------------------------------------------
# Corner: state_machines / approval_level2_before_level1_out_of_order
# ---------------------------------------------------------------------------
def test_approval_level2_before_level1_out_of_order(api):
    """PRD §3.5: "A step may be acted on only if it is the lowest-level pending step for
    its invoice and the parent invoice is still in `PENDING_APPROVAL`; acting on a step
    that is not the lowest pending step is rejected with `ERR_APPROVAL_OUT_OF_ORDER`."

    Design: Corner/state_machines/approval_level2_before_level1_out_of_order
    """
    create_gl_account()
    vendor = create_vendor(legal_name="Ord", payment_method="ACH")
    create_approval_route(min_amount_cents=0, max_amount_cents=50000, required_levels=1)
    create_approval_route(min_amount_cents=50000, max_amount_cents=1_000_000_000, required_levels=2)
    inv = create_lined_invoice(vendor["id"], 60000, invoice_number="ORD-1")
    code_invoice(inv["id"])
    validate_success(api.submit_invoice_for_approval(inv["id"], CLERK), 200)
    steps = sorted(_steps(inv["id"]), key=lambda s: s["level"])
    assert len(steps) == 2
    resp = api.approve_step(steps[1]["id"], APPROVER)  # level 2 while level 1 pending
    validate_error(resp, "ERR_APPROVAL_OUT_OF_ORDER", 409)


# ---------------------------------------------------------------------------
# Corner: validations / submit_approval_no_route_rejected
# ---------------------------------------------------------------------------
def test_submit_approval_no_route_rejected(api):
    """PRD §3.5: "If no approval route covers the invoice total — a gap in the tier
    table — submission is rejected with `ERR_NO_APPROVAL_ROUTE`."

    Design: Corner/validations/submit_approval_no_route_rejected
    """
    create_gl_account()
    vendor = create_vendor(legal_name="NoR", payment_method="ACH")
    create_approval_route(min_amount_cents=0, max_amount_cents=10000, required_levels=1)
    inv = create_lined_invoice(vendor["id"], 50000, invoice_number="NOR-1")
    code_invoice(inv["id"])
    resp = api.submit_invoice_for_approval(inv["id"], CLERK)
    validate_error(resp, "ERR_NO_APPROVAL_ROUTE", 422)


# ---------------------------------------------------------------------------
# Difficulty: transitive_cascade / reject_cascade_steps_then_po_matched_depth2
# Reject step -> invoice REJECTED -> PO.matched_amount debited back. (>=2 tests.)
# THREE_WAY invoice 100500 vs ordered 100000 received 100000 -> variance 500
# (within tol 2000) -> MATCHED, PO matched 100500.
# ---------------------------------------------------------------------------
def _setup_matched_for_reject():
    create_gl_account()
    vendor = create_vendor(legal_name="Acme", payment_method="ACH")
    create_approval_route(min_amount_cents=0, max_amount_cents=1_000_000_000, required_levels=1)
    po = create_purchase_order(vendor["id"], ordered_amount_cents=100000)
    create_posted_receipt(po["id"], 100000)
    inv = create_lined_invoice(vendor["id"], 100500, po_id=po["id"], invoice_number="INV-REJ",
                               invoice_date="2026-05-10")
    code_invoice(inv["id"])
    validate_success(api_client.submit_invoice_for_approval(inv["id"], CLERK), 200)
    step = _steps(inv["id"])[0]
    return vendor, po, inv, step


def test_reject_step_moves_invoice_and_step_to_rejected(api):
    """PRD §3.5: "Rejecting a step is the destructive branch: the targeted step moves to
    `REJECTED` with `acted_by` recorded, every higher-level still-pending step on the
    same invoice is cascaded to `REJECTED`, the invoice itself moves to `REJECTED`".

    Design: Difficulty/transitive_cascade/reject_cascade_steps_then_po_matched_depth2
    """
    vendor, po, inv, step = _setup_matched_for_reject()
    resp = api.reject_step(step["id"], APPROVER)
    data = validate_success(resp, 200)
    assert data["status"] == "REJECTED"
    inv_after = validate_success(api.get_invoice(inv["id"], MGR), 200)
    assert inv_after["status"] == "REJECTED"


def test_reject_step_compensates_po_matched_amount(api):
    """PRD §3.5: "the match-time ledger debit is compensated by decrementing the parent
    purchase order's `matched_amount_cents` by this invoice's total (reopening the PO if
    it had closed)."

    Design: Difficulty/transitive_cascade/reject_cascade_steps_then_po_matched_depth2
    """
    vendor, po, inv, step = _setup_matched_for_reject()
    # Before reject, the matched ledger carries this invoice's total.
    po_before = validate_success(api.get_purchase_order(po["id"], MGR), 200)
    assert po_before["matched_amount_cents"] == 100500
    validate_success(api.reject_step(step["id"], APPROVER), 200)
    po_after = validate_success(api.get_purchase_order(po["id"], MGR), 200)
    assert po_after["matched_amount_cents"] == 0
