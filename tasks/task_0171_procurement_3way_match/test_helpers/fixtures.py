"""Composite setup helpers for multi-step procurement test prerequisites (PRD §3).

These encapsulate the long source-to-settle preambles (vendor -> category ->
requisition -> approval -> RFQ -> quote -> award -> PO -> receipt -> invoice ->
match) so individual tests can focus on their single assertion. Every helper
builds its preconditions from scratch against an empty database, using only
PRD-declared endpoints, and uses the lenient get_success_data() validator so a
setup failure surfaces as a clear error rather than a confusing assertion.

Operator-id threading: all roles are opaque (PRD §2.1), but segregation-of-duties
checks compare recorded operator ids. The default ids keep the happy path legal
(the approver/receiver/clerk/matcher are never the requesting buyer).
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from . import factories as F
from .constants import TEST_DEFAULTS
from .test_users import (
    make_admin_headers, make_buyer_headers, make_approver_headers,
    make_receiver_headers, make_matcher_headers, make_clerk_headers,
)

# Canonical operator ids used by these fixtures.
ADMIN = "admin-a1"
BUYER = "buyer-b1"
APPROVER_MGR = "approver-mgr"
APPROVER_DIR = "approver-dir"
APPROVER_CFO = "approver-cfo"
RECEIVER = "receiver-r1"
MATCHER = "matcher-m1"
CLERK = "clerk-c1"

ADMIN_H = make_admin_headers(ADMIN)
BUYER_H = make_buyer_headers(BUYER)
RECEIVER_H = make_receiver_headers(RECEIVER)
MATCHER_H = make_matcher_headers(MATCHER)
CLERK_H = make_clerk_headers(CLERK)

# Default deterministic clock instant for time-based setups.
DEFAULT_CLOCK = TEST_DEFAULTS["DEFAULT_CLOCK"]


# ---------------------------------------------------------------------------
# Primitive setup steps
# ---------------------------------------------------------------------------
def set_clock(instant=DEFAULT_CLOCK):
    """Pin the server clock (PRD §2.4) for deterministic created_at / time comparisons."""
    return get_success_data(api_client.set_clock(instant, ADMIN_H))


def create_vendor(tax_id, name="Vendor V", grace_days=None):
    payload = F.create_vendor_payload(name=name, tax_id=tax_id)
    if grace_days is not None:
        payload["grace_days"] = grace_days
    return get_success_data(api_client.create_vendor(payload, ADMIN_H))


def create_category(code, preferred_vendor_id=None,
                    approval_threshold_cents=None, director_threshold_cents=None,
                    name="Category"):
    payload = F.create_spend_category_payload(name=name, code=code)
    if approval_threshold_cents is not None:
        payload["approval_threshold_cents"] = approval_threshold_cents
    if director_threshold_cents is not None:
        payload["director_threshold_cents"] = director_threshold_cents
    if preferred_vendor_id is not None:
        payload["preferred_vendor_id"] = preferred_vendor_id
    return get_success_data(api_client.create_spend_category(payload, ADMIN_H))


def setup_vendor_and_category(tax_id="TAX-VC", code="VCCAT", grace_days=None,
                              approval_threshold_cents=None, director_threshold_cents=None):
    """Vendor (preferred) + category referencing it. Returns (vendor, category)."""
    vendor = create_vendor(tax_id, grace_days=grace_days)
    category = create_category(
        code, preferred_vendor_id=vendor["id"],
        approval_threshold_cents=approval_threshold_cents,
        director_threshold_cents=director_threshold_cents,
    )
    return vendor, category


# ---------------------------------------------------------------------------
# Tier 1/2: Requisition lifecycle
# ---------------------------------------------------------------------------
def create_draft_requisition(category_id, lines=None, buyer_id=BUYER, title="Req"):
    """Create a DRAFT requisition. Returns the requisition."""
    return get_success_data(api_client.create_requisition(
        F.create_requisition_payload(category_id, lines=lines, title=title),
        make_buyer_headers(buyer_id),
    ))


def submit_requisition(req_id, buyer_id=BUYER):
    return get_success_data(api_client.submit_requisition(req_id, make_buyer_headers(buyer_id)))


def create_pending_requisition(category_id, lines=None, buyer_id=BUYER, title="Req"):
    """DRAFT -> PENDING_APPROVAL. Returns the submitted requisition."""
    req = create_draft_requisition(category_id, lines=lines, buyer_id=buyer_id, title=title)
    submit_requisition(req["id"], buyer_id=buyer_id)
    return get_success_data(api_client.get_requisition(req["id"], BUYER_H))


def approve_all_steps(req_id, num_levels):
    """Approve each pending step in ascending order using distinct approver ids.

    Distinct approver ids avoid any cross-step identity collision and are never
    the requesting buyer, so segregation-of-duties holds. Returns the requisition.
    """
    approvers = [APPROVER_MGR, APPROVER_DIR, APPROVER_CFO]
    for i in range(num_levels):
        get_success_data(api_client.approve_requisition(
            req_id, {"decision": "APPROVE"}, make_approver_headers(approvers[i]),
        ))
    return get_success_data(api_client.get_requisition(req_id, BUYER_H))


def create_approved_requisition(category_id, lines=None, num_levels=1,
                                buyer_id=BUYER, title="Req"):
    """Create -> submit -> fully approve. Returns the APPROVED requisition."""
    req = create_pending_requisition(category_id, lines=lines, buyer_id=buyer_id, title=title)
    return approve_all_steps(req["id"], num_levels)


# ---------------------------------------------------------------------------
# Tier 2/3: Sourcing (RFQ + Quote + award)
# ---------------------------------------------------------------------------
def open_rfq(req_id, open_at="2026-03-01T00:00:00Z", close_at="2026-03-10T00:00:00Z", buyer_id=BUYER):
    return get_success_data(api_client.create_rfq(
        F.create_rfq_payload(req_id, open_at, close_at), make_buyer_headers(buyer_id),
    ))


def submit_quote(rfq_id, vendor_id, submitted_at="2026-03-02T00:00:00Z",
                 unit_prices=None, buyer_id=BUYER):
    return get_success_data(api_client.create_quote(
        F.create_quote_payload(rfq_id, vendor_id, submitted_at, unit_prices=unit_prices),
        make_buyer_headers(buyer_id),
    ))


def award_rfq(rfq_id, quote_id, buyer_id=BUYER):
    return get_success_data(api_client.award_rfq(
        rfq_id, {"awarded_quote_id": quote_id}, make_buyer_headers(buyer_id),
    ))


def setup_awarded_quote(vendor, category, lines=None, unit_prices=None,
                        num_levels=1, promised_lead_days=5,
                        open_at="2026-03-01T00:00:00Z", close_at="2026-03-02T00:00:00Z",
                        submitted_at="2026-03-01T06:00:00Z", title="Req"):
    """Full sourcing chain through an awarded quote on an APPROVED requisition.

    Returns (requisition, rfq, quote). `unit_prices` defaults to one A-line at
    1000 cents with the given promised_lead_days.
    """
    if lines is None:
        lines = [{"sku": "A", "description": "Item A", "quantity": 1, "estimated_unit_price_cents": 1000}]
    if unit_prices is None:
        unit_prices = [{"sku": "A", "unit_price_cents": 1000, "promised_lead_days": promised_lead_days}]
    req = create_approved_requisition(category["id"], lines=lines, num_levels=num_levels, title=title)
    rfq = open_rfq(req["id"], open_at=open_at, close_at=close_at)
    quote = submit_quote(rfq["id"], vendor["id"], submitted_at=submitted_at, unit_prices=unit_prices)
    award_rfq(rfq["id"], quote["id"])
    return req, rfq, quote


# ---------------------------------------------------------------------------
# Tier 3: Purchase orders
# ---------------------------------------------------------------------------
def issue_standard_po(vendor, category, req, quote, buyer_id=BUYER):
    return get_success_data(api_client.create_purchase_order(
        F.create_standard_po_payload(vendor["id"], category["id"], req["id"], quote["id"]),
        make_buyer_headers(buyer_id),
    ))


def issue_blanket_po(vendor, category, ceiling_amount_cents=1000000,
                     valid_from="2026-03-01T00:00:00Z", valid_to="2026-03-31T00:00:00Z",
                     buyer_id=BUYER):
    return get_success_data(api_client.create_purchase_order(
        F.create_blanket_po_payload(
            vendor["id"], category["id"], ceiling_amount_cents, valid_from, valid_to),
        make_buyer_headers(buyer_id),
    ))


def setup_standard_po(tax_id="TAX-STD", code="STDCAT", lines=None, unit_prices=None,
                      num_levels=1, promised_lead_days=5, grace_days=None,
                      approval_threshold_cents=None, director_threshold_cents=None,
                      submitted_at="2026-03-01T06:00:00Z", set_clock_first=True):
    """Empty-DB -> ISSUED STANDARD PO. Returns (vendor, category, req, quote, po)."""
    if set_clock_first:
        set_clock()
    vendor, category = setup_vendor_and_category(
        tax_id=tax_id, code=code, grace_days=grace_days,
        approval_threshold_cents=approval_threshold_cents,
        director_threshold_cents=director_threshold_cents,
    )
    req, rfq, quote = setup_awarded_quote(
        vendor, category, lines=lines, unit_prices=unit_prices, num_levels=num_levels,
        promised_lead_days=promised_lead_days, submitted_at=submitted_at,
    )
    po = issue_standard_po(vendor, category, req, quote)
    return vendor, category, req, quote, po


def setup_blanket_po(tax_id="TAX-BLK", code="BLKCAT", ceiling_amount_cents=1000000,
                     valid_from="2026-03-01T00:00:00Z", valid_to="2026-03-31T00:00:00Z"):
    """Empty-DB -> ISSUED BLANKET PO. Returns (vendor, category, po)."""
    vendor, category = setup_vendor_and_category(tax_id=tax_id, code=code)
    po = issue_blanket_po(vendor, category, ceiling_amount_cents=ceiling_amount_cents,
                          valid_from=valid_from, valid_to=valid_to)
    return vendor, category, po


def create_release(blanket_po_id, amount_cents, expected_version, lines=None, buyer_id=BUYER):
    return get_success_data(api_client.create_release_order(
        F.create_release_order_payload(blanket_po_id, amount_cents, expected_version, lines=lines),
        make_buyer_headers(buyer_id),
    ))


# ---------------------------------------------------------------------------
# Tier 3/4: Receipts and invoices
# ---------------------------------------------------------------------------
def post_receipt(po_id, received_lines, received_at="2026-03-02T00:00:00Z",
                 release_order_id=None, receiver_id=RECEIVER):
    payload = F.create_goods_receipt_payload(po_id, received_lines, received_at)
    if release_order_id is not None:
        payload["release_order_id"] = release_order_id
    return get_success_data(api_client.create_goods_receipt(payload, make_receiver_headers(receiver_id)))


def record_invoice(vendor_id, po_id, gr_id, invoice_number, lines=None, clerk_id=CLERK):
    return get_success_data(api_client.create_invoice(
        F.create_invoice_payload(vendor_id, po_id, gr_id, invoice_number, lines=lines),
        make_clerk_headers(clerk_id),
    ))


def setup_received_standard_po(tax_id="TAX-RCV", code="RCVCAT", quantity=2,
                               unit_price_cents=1000, received_qty=None,
                               received_at="2026-03-02T00:00:00Z"):
    """Empty-DB -> ISSUED STANDARD PO with a POSTED receipt.

    Returns (vendor, category, req, quote, po, receipt).
    """
    if received_qty is None:
        received_qty = quantity
    lines = [{"sku": "A", "description": "Item A", "quantity": quantity,
              "estimated_unit_price_cents": unit_price_cents}]
    unit_prices = [{"sku": "A", "unit_price_cents": unit_price_cents, "promised_lead_days": 5}]
    vendor, category, req, quote, po = setup_standard_po(
        tax_id=tax_id, code=code, lines=lines, unit_prices=unit_prices,
    )
    receipt = post_receipt(po["id"], [{"sku": "A", "received_qty": received_qty}],
                           received_at=received_at)
    return vendor, category, req, quote, po, receipt


def setup_invoice_for_match(tax_id="TAX-INV", code="INVCAT", quantity=2,
                            po_unit_price_cents=1000, received_qty=None,
                            billed_qty=None, billed_unit_price_cents=None,
                            invoice_number="INV-1", received_at="2026-03-02T00:00:00Z"):
    """Empty-DB -> an UNMATCHED invoice ready for POST /invoices/{id}/match.

    Defaults make every gate pass (billed == ordered/received). Override
    billed_qty / billed_unit_price_cents to drive specific match outcomes.
    Returns (vendor, category, po, receipt, invoice).
    """
    if received_qty is None:
        received_qty = quantity
    if billed_qty is None:
        billed_qty = quantity
    if billed_unit_price_cents is None:
        billed_unit_price_cents = po_unit_price_cents
    vendor, category, req, quote, po, receipt = setup_received_standard_po(
        tax_id=tax_id, code=code, quantity=quantity,
        unit_price_cents=po_unit_price_cents, received_qty=received_qty,
        received_at=received_at,
    )
    invoice = record_invoice(
        vendor["id"], po["id"], receipt["id"], invoice_number,
        lines=[{"sku": "A", "billed_qty": billed_qty,
                "billed_unit_price_cents": billed_unit_price_cents}],
    )
    return vendor, category, po, receipt, invoice


def setup_exception_invoice(tax_id="TAX-EXC", code="EXCCAT", quantity=2,
                            po_unit_price_cents=1000, billed_unit_price_cents=2000,
                            invoice_number="INV-EXC", received_at="2026-03-02T00:00:00Z",
                            receiver_id=RECEIVER, matcher_id=MATCHER):
    """Empty-DB -> a matched-to-EXCEPTION invoice with one OPEN MatchException.

    Uses an over-tolerance billed price so the match fails PRICE_OVER_TOLERANCE.
    Returns (vendor, category, po, receipt, invoice, exception).
    """
    set_clock()
    vendor, category = setup_vendor_and_category(tax_id=tax_id, code=code)
    lines = [{"sku": "A", "description": "Item A", "quantity": quantity,
              "estimated_unit_price_cents": po_unit_price_cents}]
    unit_prices = [{"sku": "A", "unit_price_cents": po_unit_price_cents, "promised_lead_days": 5}]
    req, rfq, quote = setup_awarded_quote(vendor, category, lines=lines, unit_prices=unit_prices)
    po = issue_standard_po(vendor, category, req, quote)
    receipt = post_receipt(po["id"], [{"sku": "A", "received_qty": quantity}],
                           received_at=received_at, receiver_id=receiver_id)
    invoice = record_invoice(
        vendor["id"], po["id"], receipt["id"], invoice_number,
        lines=[{"sku": "A", "billed_qty": quantity,
                "billed_unit_price_cents": billed_unit_price_cents}],
    )
    get_success_data(api_client.match_invoice(invoice["id"], make_matcher_headers(matcher_id)))
    excs = list_exceptions_for_invoice(invoice["id"])
    exception = excs[0] if excs else None
    return vendor, category, po, receipt, invoice, exception


def list_exceptions_for_invoice(invoice_id):
    """Return the list of match exceptions filtered to one invoice (PRD §3.7)."""
    res = api_client.list_match_exceptions(MATCHER_H, params={"invoice_id": invoice_id})
    return get_success_data(res)
