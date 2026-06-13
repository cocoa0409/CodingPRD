"""Calculation correctness: dual-variant totals, the 3-way match gate chain,
vendor-scorecard percentages, composite-score rounding, and numeric boundaries.

Covers difficulty queue rules dual_variant_calc, combinatorial_formula,
boundary_precision_check, and the corner 'calculations' section.
"""
import pytest

from test_helpers import (
    api_client, validate_success, get_success_data,
    make_approver_headers,
)
import test_helpers.fixtures as fx


# ===========================================================================
# RULE 1 — dual_variant_calc
# ===========================================================================

def test_estimated_and_committed_total_diverge_on_requisition(api):
    """PRD §3.1: "the estimated total is computed as the sum, over every requisition
    line, of that line's quantity multiplied by its estimated_unit_price_cents, and
    stored as estimated_total_cents"
    PRD §3.3: "Issuing a STANDARD order also computes the committed total for the
    source requisition - the sum, over the awarded quote's priced lines, of the
    requisition quantity for each sku multiplied by that line's quoted unit_price_cents
    - and writes it onto the requisition's committed_total_cents. This committed figure
    uses the winning vendor's actual prices and therefore diverges from the earlier
    estimated_total_cents whenever the quoted price differs from the buyer's estimate;
    both numbers are exact integer-cent sums."

    Design: Difficulty/dual_variant_calc/estimated_vs_committed_total_diverge_on_requisition
    """
    fx.set_clock("2026-03-01T00:00:00Z")
    vendor, category = fx.setup_vendor_and_category(
        tax_id="TAX-V-1", code="OFFICE",
        approval_threshold_cents=500000, director_threshold_cents=2000000,
    )
    lines = [{"sku": "A", "description": "Chair", "quantity": 10, "estimated_unit_price_cents": 60000}]
    unit_prices = [{"sku": "A", "unit_price_cents": 55000, "promised_lead_days": 10}]
    # estimated 600000 > approval 500000 -> two approval levels.
    req, rfq, quote = fx.setup_awarded_quote(
        vendor, category, lines=lines, unit_prices=unit_prices, num_levels=2,
        open_at="2026-03-02T00:00:00Z", close_at="2026-03-09T00:00:00Z",
        submitted_at="2026-03-03T00:00:00Z",
    )
    po = fx.issue_standard_po(vendor, category, req, quote)
    assert po["total_amount_cents"] == 550000

    final_req = validate_success(api.get_requisition(req["id"], fx.BUYER_H), 200)
    assert final_req["estimated_total_cents"] == 600000
    assert final_req["committed_total_cents"] == 550000
    assert final_req["committed_total_cents"] != final_req["estimated_total_cents"]


def test_on_time_strict_vs_grace_diverge_on_vendor_scorecard(api):
    """PRD §3.8: "Under the STRICT variant a receipt is on time when its received_at is
    at or before the promised date; under the GRACE variant the promised date is extended
    by the vendor's grace_days before the comparison, so the same data yields an on-time
    rate at least as high as STRICT."
    PRD §3.8: "The on-time rate is then 100 multiplied by the on-time count divided by
    the total receipt count, rounded half up to an integer percentage"

    Design: Difficulty/dual_variant_calc/on_time_strict_vs_grace_diverge_on_vendor_scorecard
    """
    fx.set_clock("2026-03-01T00:00:00Z")
    vendor = fx.create_vendor("TAX-V-2", grace_days=3)
    category = fx.create_category("OFFICE2", preferred_vendor_id=vendor["id"],
                                  approval_threshold_cents=100000000,
                                  director_threshold_cents=200000000)
    lines = [{"sku": "A", "description": "Lamp", "quantity": 5, "estimated_unit_price_cents": 1000}]
    unit_prices = [{"sku": "A", "unit_price_cents": 1000, "promised_lead_days": 10}]
    # PO issued at 2026-03-01 -> promised_date 2026-03-11.
    req, rfq, quote = fx.setup_awarded_quote(vendor, category, lines=lines, unit_prices=unit_prices)
    po = fx.issue_standard_po(vendor, category, req, quote)
    # Receipt two days past promised.
    fx.set_clock("2026-03-13T00:00:00Z")
    fx.post_receipt(po["id"], [{"sku": "A", "received_qty": 5}], received_at="2026-03-13T00:00:00Z")

    sc_strict = validate_success(api.create_vendor_scorecard(
        {"vendor_id": vendor["id"], "period_start": "2026-03-01T00:00:00Z",
         "period_end": "2026-03-20T00:00:00Z", "on_time_variant": "STRICT"}, fx.ADMIN_H), 201)
    sc_grace = validate_success(api.create_vendor_scorecard(
        {"vendor_id": vendor["id"], "period_start": "2026-03-20T00:00:00Z",
         "period_end": "2026-04-10T00:00:00Z", "on_time_variant": "GRACE"}, fx.ADMIN_H), 201)

    assert sc_strict["on_time_rate_pct"] == 0
    assert sc_grace["on_time_rate_pct"] == 100
    assert sc_grace["on_time_rate_pct"] > sc_strict["on_time_rate_pct"]


# ===========================================================================
# RULE 2 — combinatorial_formula
# ===========================================================================

def test_three_way_match_amount_gate_fails_while_per_line_gates_pass(api):
    """PRD §3.6: "As a secondary, invoice-wide check, the invoice_total_cents must be at
    most the amount ceiling, where the amount ceiling is the floor of the matched PO amount
    multiplied by one plus the amount-tolerance percentage. The matched PO amount is the
    sum, over the matched skus, of the receipt's received_qty for that sku multiplied by
    the PO line's ordered unit_price_cents. The amount tolerance is 2 percent, so the
    ceiling is the floor of the matched PO amount times 1.02."
    PRD §3.6: "then an amount-tolerance breach (AMOUNT_OVER_TOLERANCE)."

    Design: Difficulty/combinatorial_formula/three_way_match_nonlinear_gate_chain_mode_a
    """
    # billed price 1050 == floor(1000*1.05) passes per line; qty 10<=10 passes;
    # invoice_total 10500 > floor(10*1000*1.02)=10200 fails the aggregate gate.
    vendor, category, po, receipt, invoice = fx.setup_invoice_for_match(
        tax_id="TAX-V-3", code="OFFICE3", quantity=10, po_unit_price_cents=1000,
        received_qty=10, billed_qty=10, billed_unit_price_cents=1050, invoice_number="INV-1",
    )
    matched = validate_success(api.match_invoice(invoice["id"], fx.MATCHER_H), 200)
    assert invoice["invoice_total_cents"] == 10500
    assert matched["match_status"] == "EXCEPTION"

    excs = fx.list_exceptions_for_invoice(invoice["id"])
    assert len(excs) == 1
    assert excs[0]["reason"] == "AMOUNT_OVER_TOLERANCE"


def test_composite_score_round_each_then_sum(api):
    """PRD §3.8: "The composite is computed by the round-each-then-sum rule, in this
    pinned order: round half up the on-time rate times 0.5 to an integer, round half up
    the price-compliance percentage times 0.3 to an integer, round half up the reliability
    term times 0.2 to an integer, then add the three rounded integers to obtain
    composite_score. The per-component rounding is mandatory and is not the same as summing
    the weighted figures and rounding once - the two can differ by a point, and the
    per-component order is the contract."

    Design: Difficulty/combinatorial_formula/composite_score_round_each_then_sum_mode_b
    """
    fx.set_clock("2026-03-01T00:00:00Z")
    vendor = fx.create_vendor("TAX-V-4", grace_days=0)
    category = fx.create_category("OFFICE4", preferred_vendor_id=vendor["id"],
                                  approval_threshold_cents=100000000,
                                  director_threshold_cents=200000000)

    def issue_po(title, code_sfx):
        lines = [{"sku": "A", "description": "A", "quantity": 1, "estimated_unit_price_cents": 1000}]
        unit_prices = [{"sku": "A", "unit_price_cents": 1000, "promised_lead_days": 10}]
        req, rfq, quote = fx.setup_awarded_quote(vendor, category, lines=lines, unit_prices=unit_prices,
                                                 title=title)
        return fx.issue_standard_po(vendor, category, req, quote)

    # PO#1: on-time receipt (2026-03-05) + invoice MATCHES within tolerance.
    po1 = issue_po("P1", "1")
    gr1 = fx.post_receipt(po1["id"], [{"sku": "A", "received_qty": 1}], received_at="2026-03-05T00:00:00Z")
    inv1 = fx.record_invoice(vendor["id"], po1["id"], gr1["id"], "INV-CS-1",
                             lines=[{"sku": "A", "billed_qty": 1, "billed_unit_price_cents": 1000}])
    validate_success(api.match_invoice(inv1["id"], fx.MATCHER_H), 200)

    # PO#2 and PO#3: late receipt (2026-03-20) + invoices FAIL price tolerance (EXCEPTION).
    for code_sfx, num in (("2", 2), ("3", 3)):
        po = issue_po(f"P{num}", code_sfx)
        gr = fx.post_receipt(po["id"], [{"sku": "A", "received_qty": 1}], received_at="2026-03-20T00:00:00Z")
        inv = fx.record_invoice(vendor["id"], po["id"], gr["id"], f"INV-CS-{num}",
                                lines=[{"sku": "A", "billed_qty": 1, "billed_unit_price_cents": 2000}])
        validate_success(api.match_invoice(inv["id"], fx.MATCHER_H), 200)

    fx.set_clock("2026-04-01T00:00:00Z")
    sc = validate_success(api.create_vendor_scorecard(
        {"vendor_id": vendor["id"], "period_start": "2026-03-01T00:00:00Z",
         "period_end": "2026-03-31T00:00:00Z", "on_time_variant": "STRICT"}, fx.ADMIN_H), 201)

    assert sc["on_time_rate_pct"] == 33
    assert sc["exception_pct"] == 67
    assert sc["price_compliance_pct"] == 100
    # c1=rhu(33*0.5)=17, c2=rhu(100*0.3)=30, c3=rhu(33*0.2)=7 -> 54 (NOT sum-then-round 53).
    assert sc["composite_score"] == 54


# ===========================================================================
# RULE 6 — boundary_precision_check
# ===========================================================================

def test_price_tolerance_at_floor_ceiling_passes(api):
    """PRD §3.6: "The price tolerance is 5 percent, so the ceiling is the floor of the
    ordered unit price times 1.05; a billed price exactly at that floored ceiling passes,
    and one cent above it fails."

    Design: Difficulty/boundary_precision_check/price_tolerance_at_floor_ceiling_passes_one_cent_over_fails
    """
    # floor(1000*1.05) == 1050: a line billed at exactly 1050 clears the price gate
    # (PRD §3.6 price gate). billed_qty=3 against received_qty=4 keeps the invoice
    # total (3*1050=3150) within the 2% amount ceiling (floor(4*1000*1.02)=4080),
    # so the price-tolerance boundary is the only gate under test and the match
    # passes (MATCHED).
    vendor, category, po, receipt, invoice = fx.setup_invoice_for_match(
        tax_id="TAX-V-11A", code="OFFICE11A", quantity=4, po_unit_price_cents=1000,
        received_qty=4, billed_qty=3, billed_unit_price_cents=1050, invoice_number="INV-BND-OK",
    )
    matched = validate_success(api.match_invoice(invoice["id"], fx.MATCHER_H), 200)
    assert matched["match_status"] == "MATCHED"


def test_price_tolerance_one_cent_over_ceiling_fails(api):
    """PRD §3.6: "The price tolerance is 5 percent, so the ceiling is the floor of the
    ordered unit price times 1.05; a billed price exactly at that floored ceiling passes,
    and one cent above it fails."
    PRD §3.6: "then a price-tolerance breach on the first offending line taken in ascending
    sku order (PRICE_OVER_TOLERANCE)"

    Design: Difficulty/boundary_precision_check/price_tolerance_at_floor_ceiling_passes_one_cent_over_fails
    """
    # 1051 == floor(1000*1.05)+1: one cent over -> EXCEPTION PRICE_OVER_TOLERANCE.
    vendor, category, po, receipt, invoice = fx.setup_invoice_for_match(
        tax_id="TAX-V-11B", code="OFFICE11B", quantity=4, po_unit_price_cents=1000,
        received_qty=4, billed_qty=4, billed_unit_price_cents=1051, invoice_number="INV-BND-OVER",
    )
    matched = validate_success(api.match_invoice(invoice["id"], fx.MATCHER_H), 200)
    assert matched["match_status"] == "EXCEPTION"
    excs = fx.list_exceptions_for_invoice(invoice["id"])
    assert len(excs) == 1
    assert excs[0]["reason"] == "PRICE_OVER_TOLERANCE"


def test_on_time_rate_empty_receipt_set_defaults_to_100(api):
    """PRD §3.8: "when there are no receipts in the period the on-time rate is defined to
    be 100."

    Design: Difficulty/boundary_precision_check/on_time_rate_empty_receipt_set_defaults_to_100_pct
    """
    fx.set_clock("2026-03-01T00:00:00Z")
    vendor = fx.create_vendor("TAX-V-12")
    sc = validate_success(api.create_vendor_scorecard(
        {"vendor_id": vendor["id"], "period_start": "2026-03-01T00:00:00Z",
         "period_end": "2026-03-31T00:00:00Z", "on_time_variant": "STRICT"}, fx.ADMIN_H), 201)
    assert sc["on_time_rate_pct"] == 100


def test_on_time_rate_empty_receipt_set_defaults_to_100_grace_variant(api):
    """PRD §3.8: "when there are no receipts in the period the on-time rate is defined to
    be 100."

    Design: Difficulty/boundary_precision_check/on_time_rate_empty_receipt_set_defaults_to_100_pct
    """
    fx.set_clock("2026-03-01T00:00:00Z")
    vendor = fx.create_vendor("TAX-V-12G", grace_days=2)
    sc = validate_success(api.create_vendor_scorecard(
        {"vendor_id": vendor["id"], "period_start": "2026-03-01T00:00:00Z",
         "period_end": "2026-03-31T00:00:00Z", "on_time_variant": "GRACE"}, fx.ADMIN_H), 201)
    assert sc["on_time_rate_pct"] == 100


# ===========================================================================
# CORNER: calculations section
# ===========================================================================

def test_approval_matrix_at_threshold_boundary_stays_one_level(api):
    """PRD §3.1: "if the base amount is strictly greater than approval_threshold_cents it
    requires a second level ... The comparison is strict, so a base exactly equal to
    approval_threshold_cents needs only one level, while a base one cent greater needs two."

    Design: Corner/calculations/approval_matrix_at_threshold_boundary_stays_one_level
    """
    vendor, category = fx.setup_vendor_and_category(
        tax_id="TAX-CALC1", code="CALC1CAT",
        approval_threshold_cents=500000, director_threshold_cents=2000000,
    )
    lines = [{"sku": "A", "description": "A", "quantity": 10, "estimated_unit_price_cents": 50000}]
    req = fx.create_pending_requisition(category["id"], lines=lines, title="B")
    assert req["estimated_total_cents"] == 500000
    assert req["required_levels"] == 1

    steps = get_success_data(api.list_approval_steps(
        make_approver_headers("approver-mgr"), params={"requisition_id": req["id"]}))
    assert len(steps) == 1
    assert steps[0]["required_role"] == "MANAGER"


def test_approval_matrix_one_cent_over_threshold_adds_director_level(api):
    """PRD §3.1: "if the base amount is strictly greater than approval_threshold_cents it
    requires a second level ... a base one cent greater needs two."
    PRD §3.1: "with ascending level values 1, 2, and 3 mapping to required_role values
    MANAGER, DIRECTOR, and CFO respectively"

    Design: Corner/calculations/approval_matrix_one_cent_over_threshold_adds_director_level
    """
    vendor, category = fx.setup_vendor_and_category(
        tax_id="TAX-CALC2", code="CALC2CAT",
        approval_threshold_cents=500000, director_threshold_cents=2000000,
    )
    lines = [{"sku": "A", "description": "A", "quantity": 1, "estimated_unit_price_cents": 500001}]
    req = fx.create_pending_requisition(category["id"], lines=lines, title="Bp1")
    assert req["estimated_total_cents"] == 500001
    assert req["required_levels"] == 2

    steps = get_success_data(api.list_approval_steps(
        make_approver_headers("approver-mgr"), params={"requisition_id": req["id"]}))
    by_level = {s["level"]: s for s in steps}
    assert by_level[1]["required_role"] == "MANAGER"
    assert by_level[2]["required_role"] == "DIRECTOR"


def test_three_way_match_qty_over_received_returns_qty_exception(api):
    """PRD §3.6: "A line's billed quantity is within tolerance when billed_qty is at most
    the matched receipt's received_qty for that sku. The quantity tolerance is zero percent
    - a vendor may never bill more than was received."
    PRD §3.6: "then a quantity breach on the first offending line in ascending sku order
    (QTY_OVER_TOLERANCE)"

    Design: Corner/calculations/three_way_match_qty_over_received_returns_qty_exception
    """
    # ordered/received 2 but billed 3, price within tolerance.
    vendor, category, po, receipt, invoice = fx.setup_invoice_for_match(
        tax_id="TAX-CALC3", code="CALC3CAT", quantity=3, po_unit_price_cents=1000,
        received_qty=2, billed_qty=3, billed_unit_price_cents=1000, invoice_number="INV-QTY",
    )
    matched = validate_success(api.match_invoice(invoice["id"], fx.MATCHER_H), 200)
    assert matched["match_status"] == "EXCEPTION"
    excs = fx.list_exceptions_for_invoice(invoice["id"])
    assert len(excs) == 1
    assert excs[0]["reason"] == "QTY_OVER_TOLERANCE"


# ===========================================================================
# CORNER: computed fields (entities section)
# ===========================================================================

def test_requisition_estimated_total_computed_at_submit(api):
    """PRD §3.1: "the estimated total is computed as the sum, over every requisition line,
    of that line's quantity multiplied by its estimated_unit_price_cents, and stored as
    estimated_total_cents; the inputs are whole-cent integers and the sum is exact with no
    rounding."

    Design: Corner/entities/requisition_estimated_total_computed_input_ignored
    """
    vendor, category = fx.setup_vendor_and_category(tax_id="TAX-EST", code="ESTCAT")
    lines = [{"sku": "A", "description": "A", "quantity": 4, "estimated_unit_price_cents": 1000}]
    req = fx.create_pending_requisition(category["id"], lines=lines, title="Est")
    assert req["estimated_total_cents"] == 4000
    assert req["required_levels"] == 1


def test_quote_quoted_total_computed_from_unit_prices_and_req_qty(api):
    """PRD §3.2: "its quoted_total_cents is computed as the sum over its priced lines of
    unit_price_cents multiplied by the matching requisition line's quantity for that sku."

    Design: Corner/entities/quote_quoted_total_computed_from_unit_prices_and_req_qty
    """
    vendor, category = fx.setup_vendor_and_category(tax_id="TAX-QT", code="QTCAT")
    lines = [{"sku": "A", "description": "A", "quantity": 4, "estimated_unit_price_cents": 1000}]
    req = fx.create_pending_requisition(category["id"], lines=lines, title="Q")
    rfq = fx.open_rfq(req["id"])
    quote = validate_success(api.create_quote(
        {"rfq_id": rfq["id"], "vendor_id": vendor["id"], "submitted_at": "2026-03-02T00:00:00Z",
         "unit_prices": [{"sku": "A", "unit_price_cents": 1000, "promised_lead_days": 5}]},
        fx.BUYER_H), 201)
    assert quote["quoted_total_cents"] == 4000
    assert quote["status"] == "SUBMITTED"


def test_po_issuance_writes_committed_total_immediately(api):
    """PRD §3.3: "Issuing a STANDARD order also computes the committed total for the source
    requisition ... and writes it onto the requisition's committed_total_cents."
    PRD §3.3: "The order's total_amount_cents is the sum over those lines of quantity
    multiplied by unit_price_cents."

    Design: Corner/consistency_model/po_issuance_writes_committed_total_in_same_request_immediate
    """
    vendor, category = fx.setup_vendor_and_category(tax_id="TAX-CM1", code="CM1CAT")
    lines = [{"sku": "A", "description": "A", "quantity": 4, "estimated_unit_price_cents": 1000}]
    unit_prices = [{"sku": "A", "unit_price_cents": 900, "promised_lead_days": 5}]
    req, rfq, quote = fx.setup_awarded_quote(vendor, category, lines=lines, unit_prices=unit_prices)
    po = fx.issue_standard_po(vendor, category, req, quote)
    assert po["total_amount_cents"] == 3600

    fetched = validate_success(api.get_requisition(req["id"], fx.BUYER_H), 200)
    assert fetched["committed_total_cents"] == 3600


def test_is_maverick_flag_reflects_preferred_vendor(api):
    """PRD §3.3: "At issuance the system also sets the is_maverick flag: it is true when
    the order's vendor_id differs from the charged spend category's preferred_vendor_id,
    and false otherwise"

    Design: Corner/entities/is_maverick_flag_set_when_po_vendor_differs_from_preferred
    """
    v_pref = fx.create_vendor("TAX-MV-PREF", name="Pref")
    v_other = fx.create_vendor("TAX-MV-OTHER", name="Other")
    category = fx.create_category("MVCAT", preferred_vendor_id=v_pref["id"],
                                  approval_threshold_cents=100000000,
                                  director_threshold_cents=200000000)
    po_mav = validate_success(api.create_purchase_order(
        {"vendor_id": v_other["id"], "spend_category_id": category["id"], "po_type": "BLANKET",
         "ceiling_amount_cents": 500000, "valid_from": "2026-03-01T00:00:00Z",
         "valid_to": "2026-03-31T00:00:00Z"}, fx.BUYER_H), 201)
    po_ok = validate_success(api.create_purchase_order(
        {"vendor_id": v_pref["id"], "spend_category_id": category["id"], "po_type": "BLANKET",
         "ceiling_amount_cents": 500000, "valid_from": "2026-04-01T00:00:00Z",
         "valid_to": "2026-04-30T00:00:00Z"}, fx.BUYER_H), 201)
    assert po_mav["is_maverick"] is True
    assert po_ok["is_maverick"] is False
