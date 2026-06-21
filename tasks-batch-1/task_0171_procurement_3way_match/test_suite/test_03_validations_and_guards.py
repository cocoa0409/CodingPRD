"""Validation guards: precedence pairs, cross-entity state preconditions, temporal
interval overlaps, and the per-error business rule catalogue.

Covers difficulty queue rules priority_pair_validation_conflict,
cross_entity_state_dependency, resource_temporal_overlap, plus the corner
'validations' and 'errors' sections.
"""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error,
    make_approver_headers,
)
import test_helpers.fixtures as fx


# ===========================================================================
# RULE 5 — priority_pair_validation_conflict
# ===========================================================================

def test_segregation_beats_state_on_self_approve_of_draft(api):
    """PRD §2.6: "(5) segregation of duties, else ERR_SEGREGATION_OF_DUTIES (403);
    (6) state legality - the target resource is in a state from which the requested
    transition is allowed, else ERR_INVALID_STATE (409)."
    PRD §3.1: "An approver may never decide a requisition they themselves raised: if the
    acting approver's X-User-ID equals the requisition's requester_id, the decision is
    refused with ERR_SEGREGATION_OF_DUTIES."

    Design: Difficulty/priority_pair_validation_conflict/segregation_beats_state_on_self_approve_of_draft_requisition
    """
    vendor, category = fx.setup_vendor_and_category(tax_id="TAX-V-9", code="OFFICE9")
    # DRAFT (never submitted) requisition raised by buyer-b1.
    req = fx.create_draft_requisition(category["id"], title="Glue", buyer_id="buyer-b1")
    # buyer-b1 acts as Approver on its own requisition: SoD (5) beats state (6).
    res = api.approve_requisition(req["id"], {"decision": "APPROVE"},
                                  make_approver_headers("buyer-b1"))
    validate_error(res, "ERR_SEGREGATION_OF_DUTIES")


def test_existence_beats_temporal_on_quote_with_missing_rfq(api):
    """PRD §2.6: "(3) existence - every path or body resource id resolves, validated
    left-to-right, else ERR_NOT_FOUND (404)"
    PRD §2.5: "every referenced id must resolve to an existing resource. Ids are validated
    left-to-right in the order they appear (path id first, then body references in
    declaration order), and the first id that fails to resolve yields ERR_NOT_FOUND
    (HTTP 404). This existence check runs after authentication and authorization but is
    part of the request's foundational validation, ahead of business-rule evaluation."

    Design: Difficulty/priority_pair_validation_conflict/existence_beats_temporal_on_quote_with_missing_rfq_and_bad_window
    """
    vendor = fx.create_vendor("TAX-V-10")
    # Non-existent rfq_id AND a submitted_at outside any window: existence (3) wins.
    res = api.create_quote(
        {"rfq_id": "00000000-0000-4000-8000-000000000000", "vendor_id": vendor["id"],
         "submitted_at": "1999-01-01T00:00:00Z",
         "unit_prices": [{"sku": "A", "unit_price_cents": 1000, "promised_lead_days": 5}]},
        fx.BUYER_H)
    validate_error(res, "ERR_NOT_FOUND")


# ===========================================================================
# RULE 7 — cross_entity_state_dependency
# ===========================================================================

def test_rfq_award_requires_requisition_approved(api):
    """PRD §3.2: "Two preconditions guard the award: the underlying requisition must
    already be APPROVED (otherwise ERR_REQUISITION_NOT_APPROVED), and the nominated quote
    must belong to this RFQ and still be SUBMITTED (otherwise ERR_INVALID_STATE)."

    Design: Difficulty/cross_entity_state_dependency/rfq_award_requires_requisition_approved
    """
    vendor, category = fx.setup_vendor_and_category(tax_id="TAX-V-13", code="OFFICE13")
    lines = [{"sku": "A", "description": "Nail", "quantity": 3, "estimated_unit_price_cents": 1000}]
    req = fx.create_pending_requisition(category["id"], lines=lines, title="Nails")
    rfq = fx.open_rfq(req["id"], open_at="2026-03-01T00:00:00Z", close_at="2026-03-10T00:00:00Z")
    quote = fx.submit_quote(rfq["id"], vendor["id"], submitted_at="2026-03-02T00:00:00Z")

    res = api.award_rfq(rfq["id"], {"awarded_quote_id": quote["id"]}, fx.BUYER_H)
    validate_error(res, "ERR_REQUISITION_NOT_APPROVED")
    rfq_after = validate_success(api.get_rfq(rfq["id"], fx.BUYER_H), 200)
    assert rfq_after["status"] == "OPEN"


def test_goods_receipt_requires_purchase_order_issued(api):
    """PRD §3.5: "Several preconditions guard posting: the purchase order must be ISSUED
    (otherwise ERR_INVALID_STATE)"
    PRD §3.3: "A Buyer may close it, moving it from ISSUED to CLOSED."

    Design: Difficulty/cross_entity_state_dependency/goods_receipt_requires_purchase_order_issued
    """
    vendor, category, req, quote, po, receipt = fx.setup_received_standard_po(
        tax_id="TAX-V-14", code="OFFICE14", quantity=2, unit_price_cents=1000, received_qty=2,
    )
    # Fully received -> close the PO.
    closed = validate_success(api.close_purchase_order(po["id"], {}, fx.BUYER_H), 200)
    assert closed["status"] == "CLOSED"

    res = api.create_goods_receipt(
        {"purchase_order_id": po["id"], "received_lines": [{"sku": "A", "received_qty": 1}],
         "received_at": "2026-03-03T00:00:00Z"}, fx.RECEIVER_H)
    validate_error(res, "ERR_INVALID_STATE")
    after = validate_success(api.get_purchase_order(po["id"], fx.BUYER_H), 200)
    assert after["status"] == "CLOSED"


# ===========================================================================
# RULE 8 — resource_temporal_overlap
# ===========================================================================

def test_blanket_po_closed_interval_adjacency_counts_as_overlap(api):
    """PRD §3.3: "a new BLANKET order is rejected with ERR_BLANKET_PERIOD_OVERLAP if its
    closed [valid_from, valid_to] interval overlaps the interval of any existing ISSUED
    blanket for the same vendor and spend category; because the interval is treated as
    closed, two intervals that merely touch at an endpoint (adjacency) count as overlapping."

    Design: Difficulty/resource_temporal_overlap/blanket_po_closed_interval_adjacency_counts_as_overlap
    """
    vendor, category = fx.setup_vendor_and_category(tax_id="TAX-V-15", code="OFFICE15")
    fx.issue_blanket_po(vendor, category, ceiling_amount_cents=1000000,
                        valid_from="2026-03-01T00:00:00Z", valid_to="2026-03-31T00:00:00Z")
    # Second blanket starts exactly on the first's valid_to: adjacency = overlap.
    res = api.create_purchase_order(
        {"vendor_id": vendor["id"], "spend_category_id": category["id"], "po_type": "BLANKET",
         "ceiling_amount_cents": 500000, "valid_from": "2026-03-31T00:00:00Z",
         "valid_to": "2026-04-30T00:00:00Z"}, fx.BUYER_H)
    validate_error(res, "ERR_BLANKET_PERIOD_OVERLAP")


def test_scorecard_half_open_period_adjacency_allowed_overlap_rejected(api):
    """PRD §3.8: "a new period whose half-open [period_start, period_end) window overlaps
    an existing scorecard period for the same vendor is rejected with
    ERR_SCORECARD_PERIOD_OVERLAP; because the window is half-open, adjacency (one period's
    end equal to the next period's start) is allowed."

    Design: Difficulty/resource_temporal_overlap/scorecard_half_open_period_adjacency_allowed_overlap_rejected
    """
    fx.set_clock("2026-05-01T00:00:00Z")
    vendor = fx.create_vendor("TAX-V-16")
    validate_success(api.create_vendor_scorecard(
        {"vendor_id": vendor["id"], "period_start": "2026-03-01T00:00:00Z",
         "period_end": "2026-03-31T00:00:00Z", "on_time_variant": "STRICT"}, fx.ADMIN_H), 201)
    # Adjacent period (start == prior end) is allowed.
    validate_success(api.create_vendor_scorecard(
        {"vendor_id": vendor["id"], "period_start": "2026-03-31T00:00:00Z",
         "period_end": "2026-04-30T00:00:00Z", "on_time_variant": "STRICT"}, fx.ADMIN_H), 201)
    # Interior overlap is rejected.
    res = api.create_vendor_scorecard(
        {"vendor_id": vendor["id"], "period_start": "2026-03-15T00:00:00Z",
         "period_end": "2026-04-15T00:00:00Z", "on_time_variant": "STRICT"}, fx.ADMIN_H)
    validate_error(res, "ERR_SCORECARD_PERIOD_OVERLAP")


# ===========================================================================
# CORNER: validations section
# ===========================================================================

def test_quote_outside_window_returns_quote_outside_window(api):
    """PRD §3.2: "The submission instant must fall within the RFQ's half-open window - at
    or after open_at and strictly before close_at; a submitted_at outside that window is
    rejected with ERR_QUOTE_OUTSIDE_WINDOW."

    Design: Corner/validations/quote_outside_window_returns_quote_outside_window
    """
    vendor, category = fx.setup_vendor_and_category(tax_id="TAX-VAL1", code="VAL1CAT")
    req = fx.create_pending_requisition(category["id"], title="W")
    rfq = fx.open_rfq(req["id"], open_at="2026-03-01T00:00:00Z", close_at="2026-03-10T00:00:00Z")
    # submitted_at == close_at is the exclusive end: outside the window.
    res = api.create_quote(
        {"rfq_id": rfq["id"], "vendor_id": vendor["id"], "submitted_at": "2026-03-10T00:00:00Z",
         "unit_prices": [{"sku": "A", "unit_price_cents": 1000, "promised_lead_days": 5}]},
        fx.BUYER_H)
    validate_error(res, "ERR_QUOTE_OUTSIDE_WINDOW")


def test_release_line_sum_mismatch_returns_invalid_request(api):
    """PRD §3.4: "the sum over the lines of quantity multiplied by unit_price_cents must
    equal the declared amount_cents exactly - a mismatch is rejected with
    ERR_INVALID_REQUEST."

    Design: Corner/validations/release_line_sum_mismatch_returns_invalid_request
    """
    vendor, category, po = fx.setup_blanket_po(tax_id="TAX-VAL2", code="VAL2CAT",
                                               ceiling_amount_cents=1000000)
    res = api.create_release_order(
        {"blanket_po_id": po["id"], "amount_cents": 2000,
         "lines": [{"sku": "A", "quantity": 1, "unit_price_cents": 1000}],
         "expected_purchase_order_version": po["version"]}, fx.BUYER_H)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_release_amount_over_remaining_returns_release_exceeds_ceiling(api):
    """PRD §3.4: "The draw may not exceed the headroom remaining on the blanket - if
    amount_cents is greater than the blanket's current remaining_amount_cents, the release
    is refused with ERR_RELEASE_EXCEEDS_CEILING."

    Design: Corner/validations/release_amount_over_remaining_returns_release_exceeds_ceiling
    """
    vendor, category, po = fx.setup_blanket_po(tax_id="TAX-VAL3", code="VAL3CAT",
                                               ceiling_amount_cents=1000000)
    res = api.create_release_order(
        {"blanket_po_id": po["id"], "amount_cents": 1500000,
         "lines": [{"sku": "A", "quantity": 15, "unit_price_cents": 100000}],
         "expected_purchase_order_version": po["version"]}, fx.BUYER_H)
    validate_error(res, "ERR_RELEASE_EXCEEDS_CEILING")


def test_release_against_standard_po_returns_not_blanket_po(api):
    """PRD §3.4: "The referenced purchase order must itself be a blanket: if blanket_po_id
    points at a non-BLANKET order, the release is refused with ERR_NOT_BLANKET_PO."

    Design: Corner/validations/release_against_standard_po_returns_not_blanket_po
    """
    vendor, category, req, quote, po = fx.setup_standard_po(tax_id="TAX-VAL4", code="VAL4CAT",
                                                            lines=[{"sku": "A", "description": "A",
                                                                    "quantity": 2,
                                                                    "estimated_unit_price_cents": 1000}],
                                                            set_clock_first=False)
    res = api.create_release_order(
        {"blanket_po_id": po["id"], "amount_cents": 1000,
         "lines": [{"sku": "A", "quantity": 1, "unit_price_cents": 1000}],
         "expected_purchase_order_version": po["version"]}, fx.BUYER_H)
    validate_error(res, "ERR_NOT_BLANKET_PO")


def test_receipt_over_tolerance_returns_receipt_over_tolerance(api):
    """PRD §3.5: "The cumulative received_qty per sku may not exceed the ordered quantity
    beyond the receipt tolerance; an over-delivery beyond what tolerance permits is rejected
    with ERR_RECEIPT_OVER_TOLERANCE."

    Design: Corner/validations/receipt_over_tolerance_returns_receipt_over_tolerance
    """
    vendor, category, req, quote, po = fx.setup_standard_po(
        tax_id="TAX-VAL5", code="VAL5CAT",
        lines=[{"sku": "A", "description": "A", "quantity": 2, "estimated_unit_price_cents": 1000}],
    )
    res = api.create_goods_receipt(
        {"purchase_order_id": po["id"], "received_lines": [{"sku": "A", "received_qty": 3}],
         "received_at": "2026-03-02T00:00:00Z"}, fx.RECEIVER_H)
    validate_error(res, "ERR_RECEIPT_OVER_TOLERANCE")


def test_invoice_match_without_posted_receipt_returns_no_receipt(api):
    """PRD §3.6: "The match first requires that a POSTED goods receipt is referenced by the
    invoice's goods_receipt_id; if none exists the match cannot proceed and yields
    ERR_NO_RECEIPT."

    Design: Corner/validations/invoice_match_without_receipt_returns_no_receipt
    """
    vendor, category, po, receipt, invoice = fx.setup_invoice_for_match(
        tax_id="TAX-VAL6", code="VAL6CAT", quantity=2, po_unit_price_cents=1000,
        invoice_number="INV-NR",
    )
    # Reverse the receipt before matching so no POSTED receipt remains.
    validate_success(api.reverse_goods_receipt(receipt["id"], fx.RECEIVER_H), 200)
    res = api.match_invoice(invoice["id"], fx.MATCHER_H)
    validate_error(res, "ERR_NO_RECEIPT")


def test_approve_payment_unmatched_invoice_returns_invoice_not_matched(api):
    """PRD §3.7: "A PayablesClerk may approve a matched invoice for payment, moving
    payment_status from PENDING to APPROVED_FOR_PAY; this requires the invoice's
    match_status to be MATCHED and is otherwise refused with ERR_INVOICE_NOT_MATCHED."

    Design: Corner/validations/approve_payment_unmatched_invoice_returns_invoice_not_matched
    """
    vendor, category, po, receipt, invoice = fx.setup_invoice_for_match(
        tax_id="TAX-VAL7", code="VAL7CAT", quantity=2, po_unit_price_cents=1000,
        invoice_number="INV-NM",
    )
    res = api.approve_payment(invoice["id"], fx.CLERK_H)
    validate_error(res, "ERR_INVOICE_NOT_MATCHED")


def test_approval_incomplete_after_only_first_step(api):
    """PRD §3.1: "Once the decision under consideration leaves all of the requisition's
    approval steps in APPROVED, the requisition itself advances from PENDING_APPROVAL to
    APPROVED. Attempting to drive the requisition to APPROVED while any required step is
    still PENDING - for instance approving an upper level before a lower one - is rejected
    with ERR_APPROVAL_INCOMPLETE."

    Design: Corner/validations/approval_incomplete_when_lower_step_pending_returns_approval_incomplete
    """
    vendor, category = fx.setup_vendor_and_category(
        tax_id="TAX-VAL8", code="VAL8CAT",
        approval_threshold_cents=500000, director_threshold_cents=2000000,
    )
    lines = [{"sku": "A", "description": "A", "quantity": 10, "estimated_unit_price_cents": 60000}]
    req = fx.create_pending_requisition(category["id"], lines=lines, title="TwoLvl")
    assert req["required_levels"] == 2
    # Approve only the first (MANAGER) step: the requisition must NOT yet be APPROVED.
    validate_success(api.approve_requisition(req["id"], {"decision": "APPROVE"},
                                             make_approver_headers("approver-mgr")), 200)
    after = validate_success(api.get_requisition(req["id"], fx.BUYER_H), 200)
    assert after["status"] == "PENDING_APPROVAL"


def test_missing_user_context_returns_401(api):
    """PRD §2.1: "Every request must carry two headers identifying the caller: X-User-ID,
    an opaque string identifying the acting user, and X-User-Role, naming the role under
    which they act. If either header is missing or malformed, the request is rejected with
    ERR_MISSING_USER_CONTEXT (HTTP 401) before any other processing."

    Design: Corner/validations/missing_user_context_returns_401
    """
    res = api.list_vendors({})
    validate_error(res, "ERR_MISSING_USER_CONTEXT")


# ===========================================================================
# CORNER: errors section
# ===========================================================================

def test_invoice_duplicate_number_for_vendor_returns_invalid_request(api):
    """PRD §3.6: "Its invoice_number must be unique for that vendor across all non-void
    invoices; a duplicate is rejected with ERR_INVALID_REQUEST."

    Design: Corner/errors/invoice_duplicate_number_for_vendor_returns_invalid_request
    """
    vendor, category, po, receipt, invoice = fx.setup_invoice_for_match(
        tax_id="TAX-DUP-INV", code="DUPCAT", quantity=2, po_unit_price_cents=1000,
        invoice_number="INV-DUP",
    )
    res = api.create_invoice(
        {"vendor_id": vendor["id"], "purchase_order_id": po["id"],
         "goods_receipt_id": receipt["id"], "invoice_number": "INV-DUP",
         "lines": [{"sku": "A", "billed_qty": 2, "billed_unit_price_cents": 1000}]}, fx.CLERK_H)
    validate_error(res, "ERR_INVALID_REQUEST")
