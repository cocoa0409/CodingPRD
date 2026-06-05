"""Match-exception resolution branches: resolve / write-off / escalate (PRD §3.4).
The write-off-vs-escalate branching difficulty instance gets >=2 tests.
"""
from test_helpers import (
    validate_success, validate_error,
    create_gl_account, create_vendor, create_purchase_order, create_posted_receipt,
    create_lined_invoice, code_invoice, get_first_match_exception,
    setup_breach_exception,
    TEST_USERS,
)

MGR = TEST_USERS["manager_headers"]
CLERK = TEST_USERS["clerk_headers"]


# ---------------------------------------------------------------------------
# Difficulty: non_linear_state_machine / match_exception_branch_writeoff_vs_escalate
# Small variance (4000) -> WRITTEN_OFF (zeroes invoice variance);
# large variance (20000) -> ESCALATED (variance unchanged). (>=2 tests.)
# ---------------------------------------------------------------------------
def test_writeoff_branch_zeroes_invoice_variance(api):
    """PRD §3.4: "**Writing off** the exception is permitted only when its
    `variance_cents` is at or below the write-off ceiling of 5000 cents; it moves the
    resolution to `WRITTEN_OFF`, zeroes the linked invoice's `variance_cents` (the
    write-off absorbs the variance, which distinguishes it from a plain resolve)".

    Design: Difficulty/non_linear_state_machine/match_exception_branch_writeoff_vs_escalate
    """
    # TWO_WAY invoice 104000 vs ordered 100000 -> variance 4000 (> tol 2000) -> breach.
    create_gl_account()
    vendor = create_vendor(legal_name="Acme", payment_method="ACH")
    po = create_purchase_order(vendor["id"], ordered_amount_cents=100000)
    inv = create_lined_invoice(vendor["id"], 104000, po_id=po["id"], invoice_number="INV-SM",
                               invoice_date="2026-05-10")
    code_invoice(inv["id"])
    exc = get_first_match_exception(inv["id"])
    assert exc["variance_cents"] == 4000
    resp = api.write_off_match_exception(exc["id"], CLERK)
    data = validate_success(resp, 200)
    assert data["resolution"] == "WRITTEN_OFF"
    inv_after = validate_success(api.get_invoice(inv["id"], CLERK), 200)
    assert inv_after["variance_cents"] == 0


def test_escalate_branch_leaves_invoice_variance_unchanged(api):
    """PRD §3.4: "**Escalating** the exception is permitted only when its
    `variance_cents` is strictly greater than the 5000-cent ceiling; it moves the
    resolution to `ESCALATED` and appends an `EXCEPTION_ESCALATED` audit event."

    Design: Difficulty/non_linear_state_machine/match_exception_branch_writeoff_vs_escalate
    """
    # TWO_WAY invoice 120000 vs ordered 100000 -> variance 20000 -> breach.
    create_gl_account()
    vendor = create_vendor(legal_name="Acme", payment_method="ACH")
    po = create_purchase_order(vendor["id"], ordered_amount_cents=100000)
    inv = create_lined_invoice(vendor["id"], 120000, po_id=po["id"], invoice_number="INV-LG",
                               invoice_date="2026-05-10")
    code_invoice(inv["id"])
    exc = get_first_match_exception(inv["id"])
    assert exc["variance_cents"] == 20000
    resp = api.escalate_match_exception(exc["id"], CLERK)
    data = validate_success(resp, 200)
    assert data["resolution"] == "ESCALATED"
    inv_after = validate_success(api.get_invoice(inv["id"], CLERK), 200)
    assert inv_after["variance_cents"] == 20000


# ---------------------------------------------------------------------------
# Corner: validations / writeoff_above_ceiling_rejected
# ---------------------------------------------------------------------------
def test_writeoff_above_ceiling_rejected(api):
    """PRD §3.4: "A write-off attempted on a variance above the 5000-cent ceiling is
    rejected with `ERR_WRITEOFF_LIMIT_EXCEEDED`."

    Design: Corner/validations/writeoff_above_ceiling_rejected
    """
    vendor, po, inv, exc = setup_breach_exception(
        ordered_amount_cents=100000, invoice_amount_cents=120000, two_way=True)
    assert exc["variance_cents"] == 20000
    resp = api.write_off_match_exception(exc["id"], CLERK)
    validate_error(resp, "ERR_WRITEOFF_LIMIT_EXCEEDED", 422)


# ---------------------------------------------------------------------------
# Corner: validations / escalate_below_ceiling_rejected
# ---------------------------------------------------------------------------
def test_escalate_below_ceiling_rejected(api):
    """PRD §3.4: "an escalate attempted at or below the ceiling is rejected with
    `ERR_ESCALATE_BELOW_CEILING`."

    Design: Corner/validations/escalate_below_ceiling_rejected
    """
    vendor, po, inv, exc = setup_breach_exception(
        ordered_amount_cents=100000, invoice_amount_cents=104000, two_way=True)
    assert exc["variance_cents"] == 4000
    resp = api.escalate_match_exception(exc["id"], CLERK)
    validate_error(resp, "ERR_ESCALATE_BELOW_CEILING", 422)


# ---------------------------------------------------------------------------
# Corner: validations / submit_approval_with_pending_exception_rejected
# (Recipe re-codes an invoice with a still-PENDING exception.)
# ---------------------------------------------------------------------------
def test_recode_with_pending_exception_rejected(api):
    """PRD §3.4: "When the match is run on an invoice already in `CODING_REVIEW`, it
    additionally requires that every match exception attached to that invoice has
    reached a non-`PENDING` resolution; if any exception is still pending, the match is
    rejected with `ERR_EXCEPTION_UNRESOLVED`."

    Design: Corner/validations/submit_approval_with_pending_exception_rejected
    """
    # THREE_WAY invoice 100000 vs received 80000 -> variance 20000 -> breach, PENDING exc.
    vendor, po, inv, exc = setup_breach_exception(
        ordered_amount_cents=100000, invoice_amount_cents=100000,
        received_amount_cents=80000, two_way=False)
    assert exc["resolution"] == "PENDING"
    resp = api.code_invoice(inv["id"], CLERK)
    validate_error(resp, "ERR_EXCEPTION_UNRESOLVED", 409)
