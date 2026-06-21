"""Second, complementary assertions for each difficulty-queue instance.

Each difficulty instance must be covered by >= 2 tests. The first assertion of
each lives alongside its rule family in test_01..test_04; this file adds a second
test per difficulty instance that exercises a distinct observable facet of the
same PRD rule (a different field, a different branch, or the inverse case), so the
pair jointly pins the behavior without duplicating a single assertion.
"""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    make_approver_headers,
)
import test_helpers.fixtures as fx


# ===========================================================================
# RULE 1 — dual_variant_calc
# ===========================================================================

def test_estimated_total_preserved_after_committed_total_written(api):
    """PRD §3.3: "This committed figure uses the winning vendor's actual prices and
    therefore diverges from the earlier estimated_total_cents whenever the quoted price
    differs from the buyer's estimate; both numbers are exact integer-cent sums."

    Second facet: the estimated_total_cents is NOT overwritten by PO issuance; both the
    estimated and committed totals coexist on the requisition.

    Design: Difficulty/dual_variant_calc/estimated_vs_committed_total_diverge_on_requisition
    """
    fx.set_clock("2026-03-01T00:00:00Z")
    vendor, category = fx.setup_vendor_and_category(
        tax_id="TAX-DV1B", code="DV1B",
        approval_threshold_cents=500000, director_threshold_cents=2000000,
    )
    lines = [{"sku": "A", "description": "Chair", "quantity": 10, "estimated_unit_price_cents": 60000}]
    unit_prices = [{"sku": "A", "unit_price_cents": 55000, "promised_lead_days": 10}]
    req, rfq, quote = fx.setup_awarded_quote(
        vendor, category, lines=lines, unit_prices=unit_prices, num_levels=2,
        open_at="2026-03-02T00:00:00Z", close_at="2026-03-09T00:00:00Z",
        submitted_at="2026-03-03T00:00:00Z",
    )
    before = validate_success(api.get_requisition(req["id"], fx.BUYER_H), 200)
    assert before["estimated_total_cents"] == 600000
    assert before["committed_total_cents"] is None

    fx.issue_standard_po(vendor, category, req, quote)
    after = validate_success(api.get_requisition(req["id"], fx.BUYER_H), 200)
    assert after["estimated_total_cents"] == 600000  # unchanged
    assert after["committed_total_cents"] == 550000


def test_grace_variant_promotes_late_receipt_to_on_time(api):
    """PRD §3.8: "under the GRACE variant the promised date is extended by the vendor's
    grace_days before the comparison, so the same data yields an on-time rate at least as
    high as STRICT."

    Second facet: a receipt arriving within the grace window (one day late on a 3-day grace)
    counts as on-time under GRACE, so the GRACE scorecard reads 100 while the receipt is
    genuinely after the bare promised date.

    Design: Difficulty/dual_variant_calc/on_time_strict_vs_grace_diverge_on_vendor_scorecard
    """
    fx.set_clock("2026-03-01T00:00:00Z")
    vendor = fx.create_vendor("TAX-DV2B", grace_days=3)
    category = fx.create_category("DV2B", preferred_vendor_id=vendor["id"],
                                  approval_threshold_cents=100000000,
                                  director_threshold_cents=200000000)
    lines = [{"sku": "A", "description": "Lamp", "quantity": 5, "estimated_unit_price_cents": 1000}]
    unit_prices = [{"sku": "A", "unit_price_cents": 1000, "promised_lead_days": 10}]
    req, rfq, quote = fx.setup_awarded_quote(vendor, category, lines=lines, unit_prices=unit_prices)
    po = fx.issue_standard_po(vendor, category, req, quote)
    # promised_date = 2026-03-11; receipt 2026-03-13 is 2 days late, within 3-day grace.
    fx.set_clock("2026-03-13T00:00:00Z")
    fx.post_receipt(po["id"], [{"sku": "A", "received_qty": 5}], received_at="2026-03-13T00:00:00Z")

    sc_grace = validate_success(api.create_vendor_scorecard(
        {"vendor_id": vendor["id"], "period_start": "2026-03-01T00:00:00Z",
         "period_end": "2026-03-20T00:00:00Z", "on_time_variant": "GRACE"}, fx.ADMIN_H), 201)
    assert sc_grace["on_time_rate_pct"] == 100


# ===========================================================================
# RULE 2 — combinatorial_formula
# ===========================================================================

def test_three_way_match_amount_gate_no_match_status_remains_unmatched_path(api):
    """PRD §3.6: "The match passes only when every line clears both its price gate and its
    quantity gate, the invoice-wide amount gate also holds, and a POSTED receipt exists ...
    Otherwise it fails, moving match_status to EXCEPTION and opening a MatchException."

    Second facet: the amount-gate failure produces exactly one MatchException carrying the
    invoice's vendor_id attribution, confirming the gate failed at the aggregate (not line)
    stage.

    Design: Difficulty/combinatorial_formula/three_way_match_nonlinear_gate_chain_mode_a
    """
    vendor, category, po, receipt, invoice = fx.setup_invoice_for_match(
        tax_id="TAX-CF1B", code="CF1B", quantity=10, po_unit_price_cents=1000,
        received_qty=10, billed_qty=10, billed_unit_price_cents=1050, invoice_number="INV-CF1B",
    )
    validate_success(api.match_invoice(invoice["id"], fx.MATCHER_H), 200)
    excs = fx.list_exceptions_for_invoice(invoice["id"])
    assert len(excs) == 1
    assert excs[0]["status"] == "OPEN"
    assert excs[0]["vendor_id"] == vendor["id"]
    assert excs[0]["reason"] == "AMOUNT_OVER_TOLERANCE"


def test_composite_score_components_round_half_up_individually(api):
    """PRD §3.8: "round half up the on-time rate times 0.5 to an integer, round half up the
    price-compliance percentage times 0.3 to an integer, round half up the reliability term
    times 0.2 to an integer, then add the three rounded integers to obtain composite_score."

    Second facet: assert each rounded component is consistent with the reported percentages
    (on_time 33 -> c1 17 from rhu(16.5); reliability 33 -> c3 7 from rhu(6.6)); the reported
    composite equals c1+c2+c3 and specifically not the sum-then-round value 53.

    Design: Difficulty/combinatorial_formula/composite_score_round_each_then_sum_mode_b
    """
    fx.set_clock("2026-03-01T00:00:00Z")
    vendor = fx.create_vendor("TAX-CF2B", grace_days=0)
    category = fx.create_category("CF2B", preferred_vendor_id=vendor["id"],
                                  approval_threshold_cents=100000000,
                                  director_threshold_cents=200000000)

    def issue_po(title):
        lines = [{"sku": "A", "description": "A", "quantity": 1, "estimated_unit_price_cents": 1000}]
        unit_prices = [{"sku": "A", "unit_price_cents": 1000, "promised_lead_days": 10}]
        req, rfq, quote = fx.setup_awarded_quote(vendor, category, lines=lines,
                                                 unit_prices=unit_prices, title=title)
        return fx.issue_standard_po(vendor, category, req, quote)

    po1 = issue_po("P1")
    gr1 = fx.post_receipt(po1["id"], [{"sku": "A", "received_qty": 1}], received_at="2026-03-05T00:00:00Z")
    inv1 = fx.record_invoice(vendor["id"], po1["id"], gr1["id"], "INV-CF2B-1",
                             lines=[{"sku": "A", "billed_qty": 1, "billed_unit_price_cents": 1000}])
    validate_success(api.match_invoice(inv1["id"], fx.MATCHER_H), 200)
    for num in (2, 3):
        po = issue_po(f"P{num}")
        gr = fx.post_receipt(po["id"], [{"sku": "A", "received_qty": 1}], received_at="2026-03-20T00:00:00Z")
        inv = fx.record_invoice(vendor["id"], po["id"], gr["id"], f"INV-CF2B-{num}",
                                lines=[{"sku": "A", "billed_qty": 1, "billed_unit_price_cents": 2000}])
        validate_success(api.match_invoice(inv["id"], fx.MATCHER_H), 200)

    fx.set_clock("2026-04-01T00:00:00Z")
    sc = validate_success(api.create_vendor_scorecard(
        {"vendor_id": vendor["id"], "period_start": "2026-03-01T00:00:00Z",
         "period_end": "2026-03-31T00:00:00Z", "on_time_variant": "STRICT"}, fx.ADMIN_H), 201)
    # c1=17, c2=30, c3=7 -> 54; the forbidden sum-then-round path yields 53.
    assert sc["composite_score"] == 54
    assert sc["composite_score"] != 53


# ===========================================================================
# RULE 3 — non_linear_state_machine
# ===========================================================================

def test_revise_clears_prior_approval_steps_before_resubmit(api):
    """PRD §3.1: "Revising increments revision_count by one and clears the prior ApprovalStep
    rows so that the next submission begins a fresh approval cycle (with required_levels
    recomputed against the then-current estimate)."

    Second facet: after revise (and before resubmit) the requisition is back in DRAFT with
    no PENDING approval step left from the previous cycle.

    Design: Difficulty/non_linear_state_machine/requisition_cyclic_revise_loop_increments_revision_count
    """
    vendor, category = fx.setup_vendor_and_category(tax_id="TAX-NL1B", code="NL1B")
    lines = [{"sku": "A", "description": "Pen", "quantity": 2, "estimated_unit_price_cents": 1000}]
    req = fx.create_pending_requisition(category["id"], lines=lines, title="Pens")
    validate_success(api.reject_requisition(req["id"], make_approver_headers("approver-mgr")), 200)

    revised = validate_success(api.revise_requisition(req["id"], fx.BUYER_H), 200)
    assert revised["status"] == "DRAFT"
    assert revised["revision_count"] == 1
    steps = get_success_data(api.list_approval_steps(
        make_approver_headers("approver-mgr"),
        params={"requisition_id": req["id"], "status": "PENDING"}))
    assert steps == []


def test_match_does_not_disturb_payment_dimension(api):
    """PRD §3.6: "these are two independent dimensions on one row that evolve separately."

    Second facet (inverse of the first assertion): running the match first leaves
    payment_status at its initial PENDING, and a later reject-payment only moves the payment
    dimension while match_status stays MATCHED.

    Design: Difficulty/non_linear_state_machine/invoice_parallel_match_and_payment_dimensions_evolve_independently
    """
    vendor, category, po, receipt, invoice = fx.setup_invoice_for_match(
        tax_id="TAX-NL2B", code="NL2B", quantity=4, po_unit_price_cents=1000,
        received_qty=4, billed_qty=4, billed_unit_price_cents=1000, invoice_number="INV-NL2B",
    )
    after_match = validate_success(api.match_invoice(invoice["id"], fx.MATCHER_H), 200)
    assert after_match["match_status"] == "MATCHED"
    assert after_match["payment_status"] == "PENDING"

    after_reject = validate_success(api.reject_payment(invoice["id"], fx.CLERK_H), 200)
    assert after_reject["payment_status"] == "REJECTED"
    assert after_reject["match_status"] == "MATCHED"


# ===========================================================================
# RULE 4 — transitive_cascade
# ===========================================================================

def test_requisition_cancel_also_cascades_rfq_and_quotes(api):
    """PRD §3.1: "Cancellation also cascades into sourcing: any OPEN RFQ for the requisition
    is cancelled, and each cancelled RFQ in turn voids its SUBMITTED quotes."

    Second facet: the same depth-3 cascade (req -> RFQ CANCELLED -> Quote VOIDED) is driven
    by the cancel trigger rather than reject, confirming both terminal triggers share the
    cascade.

    Design: Difficulty/transitive_cascade/requisition_reject_cascades_rfq_cancel_then_quote_void_depth3
    """
    vendor, category = fx.setup_vendor_and_category(tax_id="TAX-TC1B", code="TC1B")
    lines = [{"sku": "A", "description": "Cable", "quantity": 3, "estimated_unit_price_cents": 1000}]
    req = fx.create_pending_requisition(category["id"], lines=lines, title="Cable")
    rfq = fx.open_rfq(req["id"], open_at="2026-03-01T00:00:00Z", close_at="2026-03-10T00:00:00Z")
    quote = fx.submit_quote(rfq["id"], vendor["id"], submitted_at="2026-03-02T00:00:00Z")

    cancelled = validate_success(api.cancel_requisition(req["id"], fx.BUYER_H), 200)
    assert cancelled["status"] == "CANCELLED"
    rfq_after = validate_success(api.get_rfq(rfq["id"], fx.BUYER_H), 200)
    assert rfq_after["status"] == "CANCELLED"
    quote_after = validate_success(api.get_quote(quote["id"], fx.BUYER_H), 200)
    assert quote_after["status"] == "VOIDED"


def test_vendor_stays_approved_below_probation_threshold(api):
    """PRD §2.9: "a vendor enters PROBATION once its exception_count rises above three (that
    is, on the fourth open exception)"

    Second facet (boundary just below the trigger): after exactly three failing matches the
    vendor's exception_count is 3 - at, not above, the threshold - so it remains APPROVED.

    Design: Difficulty/transitive_cascade/invoice_match_fail_cascades_exception_then_count_then_probation_depth3
    """
    fx.set_clock("2026-03-01T00:00:00Z")
    vendor = fx.create_vendor("TAX-TC2B")
    category = fx.create_category("TC2B", preferred_vendor_id=vendor["id"],
                                  approval_threshold_cents=100000000,
                                  director_threshold_cents=200000000)
    for n in range(1, 4):  # three failing matches -> exception_count == 3
        lines = [{"sku": "A", "description": "A", "quantity": 1, "estimated_unit_price_cents": 1000}]
        unit_prices = [{"sku": "A", "unit_price_cents": 1000, "promised_lead_days": 5}]
        req, rfq, quote = fx.setup_awarded_quote(vendor, category, lines=lines,
                                                 unit_prices=unit_prices, title=f"W{n}")
        po = fx.issue_standard_po(vendor, category, req, quote)
        gr = fx.post_receipt(po["id"], [{"sku": "A", "received_qty": 1}])
        inv = fx.record_invoice(vendor["id"], po["id"], gr["id"], f"INV-TC2B-{n}",
                                lines=[{"sku": "A", "billed_qty": 1, "billed_unit_price_cents": 2000}])
        validate_success(api.match_invoice(inv["id"], fx.MATCHER_H), 200)

    v_after = validate_success(api.get_vendor(vendor["id"], fx.ADMIN_H), 200)
    assert v_after["exception_count"] == 3
    assert v_after["status"] == "APPROVED"


# ===========================================================================
# RULE 5 — priority_pair_validation_conflict
# ===========================================================================

def test_segregation_on_self_reject_of_pending_requisition(api):
    """PRD §3.1: "An approver may never decide a requisition they themselves raised: if the
    acting approver's X-User-ID equals the requisition's requester_id, the decision is
    refused with ERR_SEGREGATION_OF_DUTIES."

    Second facet: the same segregation guard fires on the reject decision path when the
    requester acts as approver on their own PENDING_APPROVAL requisition.

    Design: Difficulty/priority_pair_validation_conflict/segregation_beats_state_on_self_approve_of_draft_requisition
    """
    vendor, category = fx.setup_vendor_and_category(tax_id="TAX-PP1B", code="PP1B")
    req = fx.create_pending_requisition(category["id"], title="Glue", buyer_id="buyer-b1")
    res = api.reject_requisition(req["id"], make_approver_headers("buyer-b1"))
    validate_error(res, "ERR_SEGREGATION_OF_DUTIES")


def test_existence_beats_temporal_quote_window_alone_would_be_409(api):
    """PRD §2.5: "the first id that fails to resolve yields ERR_NOT_FOUND (HTTP 404). This
    existence check runs after authentication and authorization but is part of the request's
    foundational validation, ahead of business-rule evaluation."

    Second facet: with a valid (existing) RFQ but a bad window the request would be a 409
    ERR_QUOTE_OUTSIDE_WINDOW, confirming the 404 in the paired test is owed to existence
    pre-emption, not to the window check itself.

    Design: Difficulty/priority_pair_validation_conflict/existence_beats_temporal_on_quote_with_missing_rfq_and_bad_window
    """
    vendor, category = fx.setup_vendor_and_category(tax_id="TAX-PP2B", code="PP2B")
    req = fx.create_pending_requisition(category["id"], title="W")
    rfq = fx.open_rfq(req["id"], open_at="2026-03-01T00:00:00Z", close_at="2026-03-10T00:00:00Z")
    # Existing rfq, but submitted_at before open_at: window check (409) fires.
    res = api.create_quote(
        {"rfq_id": rfq["id"], "vendor_id": vendor["id"], "submitted_at": "1999-01-01T00:00:00Z",
         "unit_prices": [{"sku": "A", "unit_price_cents": 1000, "promised_lead_days": 5}]},
        fx.BUYER_H)
    validate_error(res, "ERR_QUOTE_OUTSIDE_WINDOW")


# ===========================================================================
# RULE 7 — cross_entity_state_dependency
# ===========================================================================

def test_rfq_award_succeeds_once_requisition_approved(api):
    """PRD §3.2: "the underlying requisition must already be APPROVED (otherwise
    ERR_REQUISITION_NOT_APPROVED) ... this transitions the RFQ from OPEN to AWARDED."

    Second facet (positive case): once the requisition is APPROVED the very same award
    succeeds, moving the RFQ to AWARDED and the winning quote to AWARDED.

    Design: Difficulty/cross_entity_state_dependency/rfq_award_requires_requisition_approved
    """
    vendor, category = fx.setup_vendor_and_category(tax_id="TAX-CE1B", code="CE1B")
    lines = [{"sku": "A", "description": "Nail", "quantity": 3, "estimated_unit_price_cents": 1000}]
    req = fx.create_approved_requisition(category["id"], lines=lines, num_levels=1, title="Nails")
    rfq = fx.open_rfq(req["id"], open_at="2026-03-01T00:00:00Z", close_at="2026-03-10T00:00:00Z")
    quote = fx.submit_quote(rfq["id"], vendor["id"], submitted_at="2026-03-02T00:00:00Z")

    awarded = validate_success(api.award_rfq(rfq["id"], {"awarded_quote_id": quote["id"]}, fx.BUYER_H), 200)
    assert awarded["status"] == "AWARDED"
    assert awarded["awarded_quote_id"] == quote["id"]
    q_after = validate_success(api.get_quote(quote["id"], fx.BUYER_H), 200)
    assert q_after["status"] == "AWARDED"


def test_goods_receipt_posts_against_issued_purchase_order(api):
    """PRD §3.5: "the purchase order must be ISSUED (otherwise ERR_INVALID_STATE)"
    PRD §3.5: "The receipt is born POSTED and records the posting receiver's identifier as
    posted_by_id."

    Second facet (positive case): posting against an ISSUED PO succeeds, producing a POSTED
    receipt - the precondition's satisfied branch.

    Design: Difficulty/cross_entity_state_dependency/goods_receipt_requires_purchase_order_issued
    """
    vendor, category, req, quote, po = fx.setup_standard_po(
        tax_id="TAX-CE2B", code="CE2B",
        lines=[{"sku": "A", "description": "Screw", "quantity": 2, "estimated_unit_price_cents": 1000}],
    )
    assert po["status"] == "ISSUED"
    receipt = validate_success(api.create_goods_receipt(
        {"purchase_order_id": po["id"], "received_lines": [{"sku": "A", "received_qty": 2}],
         "received_at": "2026-03-02T00:00:00Z"}, fx.RECEIVER_H), 201)
    assert receipt["status"] == "POSTED"
    assert receipt["posted_by_id"] == "receiver-r1"


# ===========================================================================
# RULE 8 — resource_temporal_overlap
# ===========================================================================

def test_blanket_po_non_overlapping_interval_allowed(api):
    """PRD §3.3: "a new BLANKET order is rejected with ERR_BLANKET_PERIOD_OVERLAP if its
    closed [valid_from, valid_to] interval overlaps the interval of any existing ISSUED
    blanket for the same vendor and spend category"

    Second facet (negative-of-overlap): a second blanket whose interval starts strictly
    after the first's valid_to (a gap, no touch) is admitted with 201.

    Design: Difficulty/resource_temporal_overlap/blanket_po_closed_interval_adjacency_counts_as_overlap
    """
    vendor, category = fx.setup_vendor_and_category(tax_id="TAX-RT1B", code="RT1B")
    fx.issue_blanket_po(vendor, category, ceiling_amount_cents=1000000,
                        valid_from="2026-03-01T00:00:00Z", valid_to="2026-03-31T00:00:00Z")
    # Starts 2026-04-01, strictly after 2026-03-31: no overlap, no adjacency.
    po2 = validate_success(api.create_purchase_order(
        {"vendor_id": vendor["id"], "spend_category_id": category["id"], "po_type": "BLANKET",
         "ceiling_amount_cents": 500000, "valid_from": "2026-04-01T00:00:00Z",
         "valid_to": "2026-04-30T00:00:00Z"}, fx.BUYER_H), 201)
    assert po2["status"] == "ISSUED"


def test_scorecard_adjacent_period_admitted_with_201(api):
    """PRD §3.8: "because the window is half-open, adjacency (one period's end equal to the
    next period's start) is allowed."

    Second facet: the adjacency branch isolated on its own - an adjacent second period
    (start == prior end) is created with 201.

    Design: Difficulty/resource_temporal_overlap/scorecard_half_open_period_adjacency_allowed_overlap_rejected
    """
    fx.set_clock("2026-05-01T00:00:00Z")
    vendor = fx.create_vendor("TAX-RT2B")
    validate_success(api.create_vendor_scorecard(
        {"vendor_id": vendor["id"], "period_start": "2026-03-01T00:00:00Z",
         "period_end": "2026-03-31T00:00:00Z", "on_time_variant": "STRICT"}, fx.ADMIN_H), 201)
    sc2 = validate_success(api.create_vendor_scorecard(
        {"vendor_id": vendor["id"], "period_start": "2026-03-31T00:00:00Z",
         "period_end": "2026-04-30T00:00:00Z", "on_time_variant": "STRICT"}, fx.ADMIN_H), 201)
    assert sc2["status"] == "FINAL"


# ===========================================================================
# RULE 9 — compensating_invariant
# ===========================================================================

def test_blanket_remaining_decrements_on_release_before_restore(api):
    """PRD §3.4: "On a successful create the release is born OPEN, the blanket's
    remaining_amount_cents is decremented by amount_cents, and the blanket's version is
    incremented by one (its updated_at refreshing accordingly)."

    Second facet: the forward (debit) leg of the invariant in isolation - the create both
    decrements remaining_amount_cents and bumps the blanket version by one.

    Design: Difficulty/compensating_invariant/blanket_remaining_ceiling_conserved_on_release_create_then_cancel
    """
    vendor, category, po = fx.setup_blanket_po(tax_id="TAX-CI1B", code="CI1B",
                                               ceiling_amount_cents=1000000)
    base_version = po["version"]
    fx.create_release(po["id"], 300000, base_version,
                      lines=[{"sku": "A", "quantity": 3, "unit_price_cents": 100000}])
    po_after = validate_success(api.get_purchase_order(po["id"], fx.BUYER_H), 200)
    assert po_after["remaining_amount_cents"] == 700000
    assert po_after["version"] == base_version + 1


def test_receipt_post_then_reverse_returns_receipt_to_reversed_terminal(api):
    """PRD §3.5: "A receiver may reverse a POSTED receipt, moving it from POSTED to the
    terminal REVERSED."
    PRD §3.5: "Reversing decrements each affected PO line's received_total by that receipt's
    received_qty per sku"

    Second facet: partial reversal accounting - posting 3 then reversing leaves received_total
    back at 0 and the receipt in the terminal REVERSED state.

    Design: Difficulty/compensating_invariant/po_received_quantity_ledger_conserved_on_receipt_post_then_reverse
    """
    vendor, category, req, quote, po = fx.setup_standard_po(
        tax_id="TAX-CI2B", code="CI2B",
        lines=[{"sku": "A", "description": "Rod", "quantity": 5, "estimated_unit_price_cents": 1000}],
    )
    receipt = fx.post_receipt(po["id"], [{"sku": "A", "received_qty": 3}])
    po_after_post = validate_success(api.get_purchase_order(po["id"], fx.BUYER_H), 200)
    line = next(ln for ln in po_after_post["lines"] if ln["sku"] == "A")
    assert line["received_total"] == 3

    reversed_receipt = validate_success(api.reverse_goods_receipt(receipt["id"], fx.RECEIVER_H), 200)
    assert reversed_receipt["status"] == "REVERSED"
    po_final = validate_success(api.get_purchase_order(po["id"], fx.BUYER_H), 200)
    line_final = next(ln for ln in po_final["lines"] if ln["sku"] == "A")
    assert line_final["received_total"] == 0
