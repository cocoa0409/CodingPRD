"""Entity creation/retrieval, input validation, listing/pagination, foreign-key
reverse-reachability filters, and role-based access control.

Covers the corner 'entities', 'endpoints' (listing), and 'rbac' sections.
"""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    make_approver_headers,
)
import test_helpers.fixtures as fx


# ===========================================================================
# CORNER: entities — creation / not-found / required / constraints / FK
# ===========================================================================

def test_create_vendor_returns_201_with_defaults(api):
    """PRD §2.9: "a computed exception_count that starts at 0, and a status that is APPROVED
    on registration."
    PRD §2.9: "an optional grace_days delivery-grace window that defaults to 0"
    PRD §2.4: "an integer version that begins at 1 on creation"

    Design: Corner/entities/create_vendor_returns_201_with_defaults_applied
    """
    res = api.create_vendor({"name": "Acme", "tax_id": "TAX-ACME"}, fx.ADMIN_H)
    vendor = validate_success(res, 201)
    assert vendor["status"] == "APPROVED"
    assert vendor["exception_count"] == 0
    assert vendor["grace_days"] == 0
    assert vendor["version"] == 1


def test_get_vendor_nonexistent_returns_not_found(api):
    """PRD §2.5: "every referenced id must resolve to an existing resource ... the first id
    that fails to resolve yields ERR_NOT_FOUND (HTTP 404)."

    Design: Corner/entities/get_vendor_nonexistent_returns_not_found
    """
    res = api.get_vendor("00000000-0000-4000-8000-0000000000aa", fx.ADMIN_H)
    validate_error(res, "ERR_NOT_FOUND")


def test_create_spend_category_missing_code_returns_invalid_request(api):
    """PRD §2.6: "(4) request well-formedness - required fields present ... else
    ERR_INVALID_REQUEST (400)"
    PRD §2.9: "A spend category carries a display name, a code that must be unique
    (uppercase) across all non-archived categories"

    Design: Corner/entities/create_spend_category_missing_required_code_returns_invalid_request
    """
    res = api.create_spend_category(
        {"name": "NoCode", "approval_threshold_cents": 1000, "director_threshold_cents": 2000},
        fx.ADMIN_H)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_create_spend_category_director_below_approval_returns_invalid_request(api):
    """PRD §2.9: "a category is rejected at creation with ERR_INVALID_REQUEST if
    director_threshold_cents is less than approval_threshold_cents"

    Design: Corner/entities/create_spend_category_director_below_approval_returns_invalid_request
    """
    res = api.create_spend_category(
        {"name": "Bad", "code": "BAD", "approval_threshold_cents": 5000,
         "director_threshold_cents": 4000}, fx.ADMIN_H)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_create_vendor_duplicate_tax_id_returns_invalid_request(api):
    """PRD §2.9: "a tax_id unique across all non-terminal vendors (a registration whose
    tax_id duplicates a non-terminal vendor's is rejected with ERR_INVALID_REQUEST)"

    Design: Corner/entities/create_vendor_duplicate_tax_id_returns_invalid_request
    """
    validate_success(api.create_vendor({"name": "V1", "tax_id": "TAX-DUP"}, fx.ADMIN_H), 201)
    res = api.create_vendor({"name": "V2", "tax_id": "TAX-DUP"}, fx.ADMIN_H)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_create_requisition_non_positive_quantity_returns_invalid_request(api):
    """PRD §3.1: "Both quantity and estimated_unit_price_cents on every line must be
    strictly positive."
    PRD §2.6: "all quantities and prices strictly greater than zero ... else
    ERR_INVALID_REQUEST (400)"

    Design: Corner/entities/create_requisition_non_positive_quantity_returns_invalid_request
    """
    vendor, category = fx.setup_vendor_and_category(tax_id="TAX-RQ", code="RQCAT")
    res = api.create_requisition(
        {"spend_category_id": category["id"], "title": "Bad",
         "lines": [{"sku": "A", "description": "A", "quantity": 0,
                    "estimated_unit_price_cents": 1000}]}, fx.BUYER_H)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_release_order_fk_must_reference_existing_blanket_po(api):
    """PRD §2.5: "every referenced id must resolve to an existing resource. Ids are
    validated left-to-right ... and the first id that fails to resolve yields ERR_NOT_FOUND
    (HTTP 404). This existence check runs after authentication and authorization but is part
    of the request's foundational validation, ahead of business-rule evaluation."

    Design: Corner/entities/release_order_fk_must_reference_existing_blanket_po
    """
    vendor, category, po = fx.setup_blanket_po(tax_id="TAX-FKNF", code="FKNFCAT",
                                               ceiling_amount_cents=1000000)
    # A real version captured, but the release targets a non-existent blanket id.
    res = api.create_release_order(
        {"blanket_po_id": "00000000-0000-4000-8000-0000000000bb", "amount_cents": 1000,
         "lines": [{"sku": "A", "quantity": 1, "unit_price_cents": 1000}],
         "expected_purchase_order_version": po["version"]}, fx.BUYER_H)
    validate_error(res, "ERR_NOT_FOUND")


# ===========================================================================
# CORNER: endpoints — pagination and FK reverse-reachability filters
# ===========================================================================

def test_list_vendors_pagination_envelope_fields(api):
    """PRD §2.3: "The meta block of a list response carries the four pagination fields
    limit, offset, total_count (the count of all matching resources before the page window
    is applied), and has_more (true when resources remain beyond the current window)."

    Design: Corner/endpoints/list_vendors_pagination_envelope_fields_present
    """
    validate_success(api.create_vendor({"name": "V1", "tax_id": "TAX-PG1"}, fx.ADMIN_H), 201)
    validate_success(api.create_vendor({"name": "V2", "tax_id": "TAX-PG2"}, fx.ADMIN_H), 201)
    data, meta = validate_paginated(api.list_vendors(fx.ADMIN_H, params={"limit": 1, "offset": 0}))
    assert len(data) == 1
    assert meta["total_count"] == 2
    assert meta["has_more"] is True


def test_approval_steps_filtered_list_by_requisition(api):
    """PRD §3.1: "Each step also records the requisition_id it belongs to."
    PRD §3.1: "Approval steps can be retrieved individually or listed; the listing can be
    narrowed by requisition_id and by step status."

    Design: Corner/endpoints/approval_steps_filtered_list_finds_children_by_requisition_id
    """
    vendor, category = fx.setup_vendor_and_category(tax_id="TAX-AS1", code="AS1CAT")
    req = fx.create_pending_requisition(category["id"], title="AS")
    data, meta = validate_paginated(api.list_approval_steps(
        make_approver_headers("approver-mgr"), params={"requisition_id": req["id"]}))
    assert len(data) == 1
    assert data[0]["requisition_id"] == req["id"]
    assert data[0]["required_role"] == "MANAGER"


def test_match_exceptions_filtered_list_by_vendor(api):
    """PRD §3.7: "The exception denormalizes the vendor_id from the invoice so that it can
    be attributed to the vendor's scorecard."
    PRD §3.7: "Match exceptions can be retrieved and listed, the listing filterable by
    invoice_id, by vendor_id, and by status."

    Design: Corner/endpoints/match_exceptions_filtered_list_by_vendor_finds_children
    """
    vendor, category, po, receipt, invoice, exception = fx.setup_exception_invoice(
        tax_id="TAX-ME1", code="ME1CAT", invoice_number="INV-ME",
    )
    data, meta = validate_paginated(api.list_match_exceptions(
        fx.MATCHER_H, params={"vendor_id": vendor["id"]}))
    assert len(data) == 1
    assert data[0]["vendor_id"] == vendor["id"]
    assert data[0]["status"] == "OPEN"


def test_vendor_scorecards_filtered_list_by_vendor(api):
    """PRD §3.8: "Scorecards can be retrieved and listed, the listing filterable by
    vendor_id."
    PRD §3.8: "A scorecard is born FINAL and is never mutated thereafter."

    Design: Corner/endpoints/vendor_scorecards_filtered_list_by_vendor_finds_children
    """
    fx.set_clock("2026-04-01T00:00:00Z")
    vendor = fx.create_vendor("TAX-VSC1")
    validate_success(api.create_vendor_scorecard(
        {"vendor_id": vendor["id"], "period_start": "2026-03-01T00:00:00Z",
         "period_end": "2026-03-31T00:00:00Z", "on_time_variant": "STRICT"}, fx.ADMIN_H), 201)
    data, meta = validate_paginated(api.list_vendor_scorecards(
        fx.ADMIN_H, params={"vendor_id": vendor["id"]}))
    assert len(data) == 1
    assert data[0]["vendor_id"] == vendor["id"]
    assert data[0]["status"] == "FINAL"


def test_release_orders_filtered_list_by_blanket_po(api):
    """PRD §3.4: "Releases can be retrieved and listed, the listing filterable by
    blanket_po_id and by status."

    Design: Corner/endpoints/release_orders_filtered_list_by_blanket_po_finds_children
    """
    vendor, category, po = fx.setup_blanket_po(tax_id="TAX-RO1", code="RO1CAT",
                                               ceiling_amount_cents=1000000)
    rel = fx.create_release(po["id"], 200000, po["version"],
                            lines=[{"sku": "A", "quantity": 2, "unit_price_cents": 100000}])
    data, meta = validate_paginated(api.list_release_orders(
        fx.BUYER_H, params={"blanket_po_id": po["id"]}))
    assert len(data) == 1
    assert data[0]["blanket_po_id"] == po["id"]
    assert data[0]["status"] == "OPEN"


def test_goods_receipts_filtered_list_by_purchase_order(api):
    """PRD §3.5: "Goods receipts can be retrieved and listed, the listing filterable by
    purchase_order_id, by release_order_id, and by status."

    Design: Corner/endpoints/goods_receipts_filtered_list_by_purchase_order_finds_children
    """
    vendor, category, req, quote, po, receipt = fx.setup_received_standard_po(
        tax_id="TAX-GR1", code="GR1CAT", quantity=2, unit_price_cents=1000, received_qty=2,
    )
    data, meta = validate_paginated(api.list_goods_receipts(
        fx.RECEIVER_H, params={"purchase_order_id": po["id"]}))
    assert len(data) == 1
    assert data[0]["purchase_order_id"] == po["id"]
    assert data[0]["status"] == "POSTED"


def test_invoices_filtered_list_by_purchase_order(api):
    """PRD §3.6: "Invoices can be retrieved and listed, the listing filterable by vendor_id,
    purchase_order_id, goods_receipt_id, match_status, and payment_status."

    Design: Corner/endpoints/invoices_filtered_list_by_purchase_order_finds_children
    """
    vendor, category, po, receipt, invoice = fx.setup_invoice_for_match(
        tax_id="TAX-IV1", code="IV1CAT", quantity=2, po_unit_price_cents=1000,
        invoice_number="INV-IV",
    )
    data, meta = validate_paginated(api.list_invoices(
        fx.CLERK_H, params={"purchase_order_id": po["id"]}))
    assert len(data) == 1
    assert data[0]["purchase_order_id"] == po["id"]
    assert data[0]["match_status"] == "UNMATCHED"


def test_rfqs_filtered_list_by_requisition(api):
    """PRD §3.2: "RFQs can be listed and filtered by requisition_id, by awarded_quote_id,
    and by status."
    PRD §3.2: "its round_index is set to the count of RFQs already opened for that
    requisition - a 0-based negotiation round"

    Design: Corner/endpoints/rfqs_filtered_list_by_requisition_finds_children
    """
    vendor, category = fx.setup_vendor_and_category(tax_id="TAX-RQ2", code="RQ2CAT")
    req = fx.create_pending_requisition(category["id"], title="RQ")
    fx.open_rfq(req["id"], open_at="2026-03-01T00:00:00Z", close_at="2026-03-10T00:00:00Z")
    data, meta = validate_paginated(api.list_rfqs(fx.BUYER_H, params={"requisition_id": req["id"]}))
    assert len(data) == 1
    assert data[0]["requisition_id"] == req["id"]
    assert data[0]["round_index"] == 0


def test_quotes_filtered_list_by_rfq(api):
    """PRD §3.2: "Quotes can be retrieved, or listed and filtered by rfq_id, by vendor_id,
    and by status."
    PRD §3.2: "A new quote is born SUBMITTED"

    Design: Corner/endpoints/quotes_filtered_list_by_rfq_finds_children
    """
    vendor, category = fx.setup_vendor_and_category(tax_id="TAX-QF1", code="QF1CAT")
    req = fx.create_pending_requisition(category["id"], title="QF")
    rfq = fx.open_rfq(req["id"], open_at="2026-03-01T00:00:00Z", close_at="2026-03-10T00:00:00Z")
    fx.submit_quote(rfq["id"], vendor["id"], submitted_at="2026-03-02T00:00:00Z")
    data, meta = validate_paginated(api.list_quotes(fx.BUYER_H, params={"rfq_id": rfq["id"]}))
    assert len(data) == 1
    assert data[0]["rfq_id"] == rfq["id"]
    assert data[0]["status"] == "SUBMITTED"


def test_purchase_orders_filtered_list_by_requisition(api):
    """PRD §3.3: "Purchase orders can be retrieved and listed, with the listing filterable
    by vendor_id, spend_category_id, requisition_id, source_quote_id, po_type, status, and
    the boolean is_maverick."

    Design: Corner/endpoints/purchase_orders_filtered_list_by_requisition_finds_children
    """
    vendor, category, req, quote, po = fx.setup_standard_po(
        tax_id="TAX-PO1", code="PO1CAT",
        lines=[{"sku": "A", "description": "A", "quantity": 1, "estimated_unit_price_cents": 1000}],
    )
    data, meta = validate_paginated(api.list_purchase_orders(
        fx.BUYER_H, params={"requisition_id": req["id"]}))
    assert len(data) == 1
    assert data[0]["requisition_id"] == req["id"]
    assert data[0]["po_type"] == "STANDARD"


def test_spend_categories_filtered_list_by_preferred_vendor(api):
    """PRD §2.9: "The preferred_vendor_id names the contracted vendor for the category and
    is the reference point for the maverick-spend flag."

    Design: Corner/endpoints/spend_categories_filtered_list_by_preferred_vendor_finds_children
    """
    vendor = fx.create_vendor("TAX-SC1")
    category = fx.create_category("SC1CAT", preferred_vendor_id=vendor["id"],
                                  approval_threshold_cents=1000, director_threshold_cents=2000)
    data, meta = validate_paginated(api.list_spend_categories(
        fx.ADMIN_H, params={"preferred_vendor_id": vendor["id"]}))
    assert len(data) == 1
    assert data[0]["preferred_vendor_id"] == vendor["id"]


# ===========================================================================
# CORNER: rbac — forbidden roles and segregation of duties
# ===========================================================================

def test_buyer_cannot_register_vendor_returns_forbidden(api):
    """PRD §2.1: "If the headers are well-formed but the named role is not permitted to
    invoke the requested operation, the request is rejected with ERR_FORBIDDEN_FOR_ROLE
    (HTTP 403)."
    PRD §2.1: "ProcurementAdmin governs master data - spend categories, vendor registration
    and blocking, scorecards, and the test clock."

    Design: Corner/rbac/buyer_cannot_register_vendor_returns_forbidden
    """
    res = api.create_vendor({"name": "X", "tax_id": "TAX-RBAC1"}, fx.BUYER_H)
    validate_error(res, "ERR_FORBIDDEN_FOR_ROLE")


def test_matcher_cannot_record_invoice_returns_forbidden(api):
    """PRD §2.1: "If the headers are well-formed but the named role is not permitted to
    invoke the requested operation, the request is rejected with ERR_FORBIDDEN_FOR_ROLE
    (HTTP 403)."
    PRD §2.1: "PayablesClerk records invoices and drives the payment dimension (approve,
    reject, pay)."

    Design: Corner/rbac/matcher_cannot_record_invoice_returns_forbidden
    """
    vendor, category, req, quote, po, receipt = fx.setup_received_standard_po(
        tax_id="TAX-RBAC2", code="RBAC2CAT", quantity=2, unit_price_cents=1000, received_qty=2,
    )
    res = api.create_invoice(
        {"vendor_id": vendor["id"], "purchase_order_id": po["id"],
         "goods_receipt_id": receipt["id"], "invoice_number": "INV-RB",
         "lines": [{"sku": "A", "billed_qty": 2, "billed_unit_price_cents": 1000}]},
        fx.MATCHER_H)
    validate_error(res, "ERR_FORBIDDEN_FOR_ROLE")


def test_receiver_who_is_requester_cannot_post_receipt_returns_segregation(api):
    """PRD §3.5: "segregation of duties forbids the receiver from being the requisition
    requester of the order being received - if the acting receiver's X-User-ID equals the
    requester_id of the requisition behind the linked purchase order, the post is refused
    with ERR_SEGREGATION_OF_DUTIES."

    Design: Corner/rbac/receiver_who_is_requisition_requester_cannot_post_receipt_returns_segregation
    """
    # Requisition raised by buyer-b1; the same id acts as Receiver.
    vendor, category, req, quote, po = fx.setup_standard_po(
        tax_id="TAX-SOD1", code="SOD1CAT",
        lines=[{"sku": "A", "description": "A", "quantity": 2, "estimated_unit_price_cents": 1000}],
    )
    res = api.create_goods_receipt(
        {"purchase_order_id": po["id"], "received_lines": [{"sku": "A", "received_qty": 2}],
         "received_at": "2026-03-02T00:00:00Z"}, fx.make_receiver_headers("buyer-b1"))
    validate_error(res, "ERR_SEGREGATION_OF_DUTIES")


def test_matcher_who_posted_receipt_cannot_waive_exception_returns_segregation(api):
    """PRD §3.7: "Waiving carries a segregation-of-duties guard: the acting matcher may not
    be the receiver who posted the receipt behind the match - if the matcher's X-User-ID
    equals the matched receipt's posted_by_id, the waive is refused with
    ERR_SEGREGATION_OF_DUTIES."

    Design: Corner/rbac/matcher_who_posted_receipt_cannot_waive_exception_returns_segregation
    """
    # Receipt posted by user-rx, who then attempts to waive the exception.
    vendor, category, po, receipt, invoice, exception = fx.setup_exception_invoice(
        tax_id="TAX-SOD2", code="SOD2CAT", invoice_number="INV-WV", receiver_id="user-rx",
    )
    assert exception is not None
    res = api.waive_match_exception(exception["id"], fx.make_matcher_headers("user-rx"))
    validate_error(res, "ERR_SEGREGATION_OF_DUTIES")
