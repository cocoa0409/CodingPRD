"""State-machine behavior and cascade chains: requisition revise loop, invoice
parallel dimensions, requisition-reject -> RFQ/quote cascade, match-fail ->
exception -> probation cascade, terminal-state lockdowns, and bubble-up/cascade-down.

Covers difficulty queue rules non_linear_state_machine and transitive_cascade,
plus the corner 'state_machines' section.
"""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    make_approver_headers,
)
import test_helpers.fixtures as fx


# ===========================================================================
# RULE 3 — non_linear_state_machine
# ===========================================================================

def test_requisition_cyclic_revise_loop_increments_revision_count(api):
    """PRD §3.1: "The Buyer who owns a REJECTED requisition may revise it, returning it
    from REJECTED to DRAFT; this is the cyclic revise loop that lets a need be re-shopped
    and resubmitted. Revising increments revision_count by one and clears the prior
    ApprovalStep rows so that the next submission begins a fresh approval cycle"

    Design: Difficulty/non_linear_state_machine/requisition_cyclic_revise_loop_increments_revision_count
    """
    vendor, category = fx.setup_vendor_and_category(tax_id="TAX-V-5", code="OFFICE5")
    lines = [{"sku": "A", "description": "Pen", "quantity": 2, "estimated_unit_price_cents": 1000}]
    req = fx.create_pending_requisition(category["id"], lines=lines, title="Pens")
    # Reject by an approver who is not the requester.
    validate_success(api.reject_requisition(req["id"], make_approver_headers("approver-mgr")), 200)

    revised = validate_success(api.revise_requisition(req["id"], fx.BUYER_H), 200)
    assert revised["status"] == "DRAFT"
    resubmitted = validate_success(api.submit_requisition(req["id"], fx.BUYER_H), 200)
    assert resubmitted["status"] == "PENDING_APPROVAL"
    assert resubmitted["revision_count"] == 1

    steps = get_success_data(api.list_approval_steps(
        make_approver_headers("approver-mgr"), params={"requisition_id": req["id"]}))
    pending_l1 = [s for s in steps if s["level"] == 1 and s["status"] == "PENDING"]
    assert len(pending_l1) == 1


def test_invoice_match_and_payment_dimensions_evolve_independently(api):
    """PRD §3.6: "An invoice is born with match_status of UNMATCHED and payment_status of
    PENDING - these are two independent dimensions on one row that evolve separately."
    PRD §3.7: "A clerk may instead reject an invoice for payment from PENDING, moving
    payment_status to REJECTED (no match precondition applies to a rejection)."
    PRD §3.6: "The match passes only when every line clears both its price gate and its
    quantity gate ... passing moves match_status to MATCHED."

    Design: Difficulty/non_linear_state_machine/invoice_parallel_match_and_payment_dimensions_evolve_independently
    """
    vendor, category, po, receipt, invoice = fx.setup_invoice_for_match(
        tax_id="TAX-V-6", code="OFFICE6", quantity=4, po_unit_price_cents=1000,
        received_qty=4, billed_qty=4, billed_unit_price_cents=1000, invoice_number="INV-2",
    )
    assert invoice["match_status"] == "UNMATCHED"
    assert invoice["payment_status"] == "PENDING"

    after_reject = validate_success(api.reject_payment(invoice["id"], fx.CLERK_H), 200)
    assert after_reject["payment_status"] == "REJECTED"
    assert after_reject["match_status"] == "UNMATCHED"

    after_match = validate_success(api.match_invoice(invoice["id"], fx.MATCHER_H), 200)
    assert after_match["match_status"] == "MATCHED"
    assert after_match["payment_status"] == "REJECTED"


# ===========================================================================
# RULE 4 — transitive_cascade
# ===========================================================================

def test_requisition_reject_cascades_rfq_cancel_then_quote_void(api):
    """PRD §3.1: "A rejection cascades the same way - any OPEN RFQ for the requisition is
    moved to CANCELLED, which voids its SUBMITTED quotes."
    PRD §3.2: "A buyer may also cancel an OPEN RFQ outright - moving it from OPEN to
    CANCELLED and voiding its SUBMITTED quotes"

    Design: Difficulty/transitive_cascade/requisition_reject_cascades_rfq_cancel_then_quote_void_depth3
    """
    vendor, category = fx.setup_vendor_and_category(tax_id="TAX-V-7", code="OFFICE7")
    lines = [{"sku": "A", "description": "Cable", "quantity": 3, "estimated_unit_price_cents": 1000}]
    req = fx.create_pending_requisition(category["id"], lines=lines, title="Cable")
    rfq = fx.open_rfq(req["id"], open_at="2026-03-01T00:00:00Z", close_at="2026-03-10T00:00:00Z")
    quote = fx.submit_quote(rfq["id"], vendor["id"], submitted_at="2026-03-02T00:00:00Z")

    rejected = validate_success(api.reject_requisition(req["id"], make_approver_headers("approver-mgr")), 200)
    assert rejected["status"] == "REJECTED"

    rfq_after = validate_success(api.get_rfq(rfq["id"], fx.BUYER_H), 200)
    assert rfq_after["status"] == "CANCELLED"
    quote_after = validate_success(api.get_quote(quote["id"], fx.BUYER_H), 200)
    assert quote_after["status"] == "VOIDED"


def test_match_fail_cascades_exception_then_count_then_probation(api):
    """PRD §3.7: "Creating the exception then recomputes the offending vendor's
    exception_count (its count of open exceptions); if that count rises above the probation
    threshold of three open exceptions, the vendor moves from APPROVED to PROBATION."
    PRD §2.9: "a vendor enters PROBATION once its exception_count rises above three (that
    is, on the fourth open exception)"

    Design: Difficulty/transitive_cascade/invoice_match_fail_cascades_exception_then_count_then_probation_depth3
    """
    fx.set_clock("2026-03-01T00:00:00Z")
    vendor = fx.create_vendor("TAX-V-8")
    category = fx.create_category("OFFICE8", preferred_vendor_id=vendor["id"],
                                  approval_threshold_cents=100000000,
                                  director_threshold_cents=200000000)

    last_invoice_id = None
    # The probation threshold is 3; PROBATION is reached on the 4th open exception.
    for n in range(1, 5):
        lines = [{"sku": "A", "description": "A", "quantity": 1, "estimated_unit_price_cents": 1000}]
        unit_prices = [{"sku": "A", "unit_price_cents": 1000, "promised_lead_days": 5}]
        req, rfq, quote = fx.setup_awarded_quote(vendor, category, lines=lines,
                                                 unit_prices=unit_prices, title=f"W{n}")
        po = fx.issue_standard_po(vendor, category, req, quote)
        gr = fx.post_receipt(po["id"], [{"sku": "A", "received_qty": 1}])
        inv = fx.record_invoice(vendor["id"], po["id"], gr["id"], f"INV-PR-{n}",
                                lines=[{"sku": "A", "billed_qty": 1, "billed_unit_price_cents": 2000}])
        matched = validate_success(api.match_invoice(inv["id"], fx.MATCHER_H), 200)
        assert matched["match_status"] == "EXCEPTION"
        last_invoice_id = inv["id"]

    excs = fx.list_exceptions_for_invoice(last_invoice_id)
    assert len(excs) == 1
    assert excs[0]["reason"] == "PRICE_OVER_TOLERANCE"
    assert excs[0]["vendor_id"] == vendor["id"]

    v_after = validate_success(api.get_vendor(vendor["id"], fx.ADMIN_H), 200)
    assert v_after["exception_count"] == 4
    assert v_after["status"] == "PROBATION"


# ===========================================================================
# CORNER: state_machines section
# ===========================================================================

def test_requisition_initial_state_is_draft_on_create(api):
    """PRD §3.1: "On creation the requisition is born in DRAFT, its requester_id is set to
    the creating buyer's X-User-ID, and its revision_count is initialized to 0. The
    requisition's committed_total_cents remains null until a purchase order is later issued
    from it."

    Design: Corner/state_machines/requisition_initial_state_is_draft_on_create
    """
    vendor, category = fx.setup_vendor_and_category(tax_id="TAX-SM3", code="SM3CAT")
    req = fx.create_draft_requisition(category["id"], title="Init")
    assert req["status"] == "DRAFT"
    assert req["revision_count"] == 0
    assert req["committed_total_cents"] is None


def test_cancel_requisition_from_cancelled_returns_invalid_state(api):
    """PRD §3.1: "The same requester may cancel a requisition from either DRAFT or
    PENDING_APPROVAL, driving it to the terminal CANCELLED state"
    PRD §2.6: "(6) state legality - the target resource is in a state from which the
    requested transition is allowed, else ERR_INVALID_STATE (409)."

    Design: Corner/state_machines/cancel_requisition_from_cancelled_returns_invalid_state
    """
    vendor, category = fx.setup_vendor_and_category(tax_id="TAX-SM1", code="SM1CAT")
    req = fx.create_draft_requisition(category["id"], title="C")
    validate_success(api.cancel_requisition(req["id"], fx.BUYER_H), 200)

    res = api.cancel_requisition(req["id"], fx.BUYER_H)
    validate_error(res, "ERR_INVALID_STATE")
    after = validate_success(api.get_requisition(req["id"], fx.BUYER_H), 200)
    assert after["status"] == "CANCELLED"


def test_approve_requisition_while_draft_returns_invalid_state(api):
    """PRD §3.1: "Submitting a draft advances the requisition from DRAFT to
    PENDING_APPROVAL."
    PRD §3.1: "An Approver decides the pending steps in ascending level order."
    PRD §2.6: "(6) state legality - the target resource is in a state from which the
    requested transition is allowed, else ERR_INVALID_STATE (409)."

    Design: Corner/state_machines/approve_requisition_while_draft_returns_invalid_state
    """
    vendor, category = fx.setup_vendor_and_category(tax_id="TAX-SM2", code="SM2CAT")
    req = fx.create_draft_requisition(category["id"], title="D")
    res = api.approve_requisition(req["id"], {"decision": "APPROVE"},
                                  make_approver_headers("approver-mgr"))
    validate_error(res, "ERR_INVALID_STATE")


def test_revise_from_pending_approval_returns_invalid_state(api):
    """PRD §3.1: "The Buyer who owns a REJECTED requisition may revise it, returning it
    from REJECTED to DRAFT"
    PRD §2.6: "(6) state legality - the target resource is in a state from which the
    requested transition is allowed, else ERR_INVALID_STATE (409)."

    Design: Corner/state_machines/requisition_revise_from_pending_approval_returns_invalid_state
    """
    vendor, category = fx.setup_vendor_and_category(tax_id="TAX-SM8", code="SM8CAT")
    req = fx.create_pending_requisition(category["id"], title="RV")
    res = api.revise_requisition(req["id"], fx.BUYER_H)
    validate_error(res, "ERR_INVALID_STATE")


def test_pay_invoice_before_approval_returns_invalid_state(api):
    """PRD §3.7: "Finally a clerk pays an approved invoice, moving payment_status from
    APPROVED_FOR_PAY to PAID; attempting to pay an invoice that is not in APPROVED_FOR_PAY
    is refused with ERR_INVALID_STATE."

    Design: Corner/state_machines/pay_invoice_before_approval_returns_invalid_state
    """
    vendor, category, po, receipt, invoice = fx.setup_invoice_for_match(
        tax_id="TAX-SM4", code="SM4CAT", quantity=2, po_unit_price_cents=1000,
        invoice_number="INV-PAY",
    )
    res = api.pay_invoice(invoice["id"], fx.CLERK_H)
    validate_error(res, "ERR_INVALID_STATE")
    after = validate_success(api.get_invoice(invoice["id"], fx.CLERK_H), 200)
    assert after["payment_status"] == "PENDING"


def test_cancel_blanket_po_cascades_open_releases_and_restores_ceiling(api):
    """PRD §3.3: "Cancelling a BLANKET order cascades to every OPEN release against it:
    each such release is moved to CANCELLED, and as each is cancelled the release's
    amount_cents is added back to the blanket's remaining_amount_cents as a compensating
    restore."

    Design: Corner/state_machines/cancel_blanket_po_cascades_open_releases_cancelled_and_restores_ceiling
    """
    vendor, category, po = fx.setup_blanket_po(tax_id="TAX-SM5", code="SM5CAT",
                                               ceiling_amount_cents=1000000)
    rel = fx.create_release(po["id"], 300000, po["version"],
                            lines=[{"sku": "A", "quantity": 3, "unit_price_cents": 100000}])

    validate_success(api.cancel_purchase_order(po["id"], fx.BUYER_H), 200)
    po_after = validate_success(api.get_purchase_order(po["id"], fx.BUYER_H), 200)
    rel_after = validate_success(api.get_release_order(rel["id"], fx.BUYER_H), 200)
    assert po_after["status"] == "CANCELLED"
    assert rel_after["status"] == "CANCELLED"
    assert po_after["remaining_amount_cents"] == 1000000


def test_resolve_last_open_exception_bubbles_invoice_to_matched(api):
    """PRD §3.7: "Both resolving and waiving recompute the vendor's exception_count; if
    that count falls to three or fewer open exceptions and the vendor is in PROBATION, the
    vendor returns from PROBATION to APPROVED. Both also check whether any OPEN exception
    remains for the invoice: when none does, the invoice's match dimension moves from
    EXCEPTION to MATCHED."

    Design: Corner/state_machines/resolve_last_open_exception_bubbles_invoice_back_to_matched
    """
    vendor, category, po, receipt, invoice, exception = fx.setup_exception_invoice(
        tax_id="TAX-SM6", code="SM6CAT", invoice_number="INV-EXC",
    )
    assert exception is not None
    resolved = validate_success(api.resolve_match_exception(exception["id"], fx.MATCHER_H), 200)
    assert resolved["status"] == "RESOLVED"

    inv_after = validate_success(api.get_invoice(invoice["id"], fx.MATCHER_H), 200)
    assert inv_after["match_status"] == "MATCHED"
    v_after = validate_success(api.get_vendor(vendor["id"], fx.ADMIN_H), 200)
    assert v_after["exception_count"] == 0


def test_reverse_receipt_with_matched_invoice_returns_receipt_has_invoice(api):
    """PRD §3.5: "A reversal is refused with ERR_RECEIPT_HAS_INVOICE if any invoice that is
    MATCHED or in EXCEPTION references the receipt - once a receipt has anchored a completed
    or failed match it can no longer be unwound."

    Design: Corner/state_machines/reverse_receipt_with_matched_invoice_returns_receipt_has_invoice
    """
    vendor, category, po, receipt, invoice = fx.setup_invoice_for_match(
        tax_id="TAX-SM7", code="SM7CAT", quantity=2, po_unit_price_cents=1000,
        invoice_number="INV-RH",
    )
    validate_success(api.match_invoice(invoice["id"], fx.MATCHER_H), 200)
    res = api.reverse_goods_receipt(receipt["id"], fx.RECEIVER_H)
    validate_error(res, "ERR_RECEIPT_HAS_INVOICE")
    after = validate_success(api.get_goods_receipt(receipt["id"], fx.RECEIVER_H), 200)
    assert after["status"] == "POSTED"
