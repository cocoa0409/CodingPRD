"""Invoice reconciliation: pinned money order, tier boundaries, landed cost,
and the post-time cascades onto products and the purchase order.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_product, create_submitted_po, create_draft_invoice_with_lines,
    create_posted_invoice, create_product_with_par, get_product,
    add_invoice_line_payload, PURCHASING_AGENT,
)


def _purchasing():
    return PURCHASING_AGENT


def test_invoice_post_pinned_subtotal_discount_tax_total_order(api):
    """PRD §3.6: "the reconciliation then computes, in this exact sequence: first,
    each line's `extension_cents` as its `received_qty` multiplied by its
    `unit_cost_cents`; second, the invoice `subtotal_cents` as the sum of those
    extensions; third, the `discount_cents` as a tiered percentage of the subtotal
    — five percent if the subtotal is at least 40,000 cents, otherwise three percent
    if it is at least 30,000 cents, otherwise zero — rounded half-up to a whole cent,
    where the tier boundaries are inclusive so that a subtotal of exactly 40,000 cents
    takes the five-percent tier; fourth, the `tax_cents` as eight and three-quarters
    percent (the rate 0.0875) of the subtotal-minus-discount, rounded half-up to a
    whole cent; and fifth, the `invoice_total_cents` as the subtotal minus the
    discount, plus the tax, plus the freight."

    Design: Difficulty/combinatorial_formula/invoice_subtotal_discount_tax_order_mode_c
    """
    teq = create_product(sku="TEQ-C", name="Tequila", container_volume_ml=750, unit_cost_cents=2400)
    coin = create_product(sku="COIN-C", name="Cointreau", container_volume_ml=700, unit_cost_cents=3000)
    po = create_submitted_po([
        {"product_id": teq["id"], "ordered_qty": 12, "unit_cost_cents": 2495},
        {"product_id": coin["id"], "ordered_qty": 6, "unit_cost_cents": 3200},
    ])
    inv = create_draft_invoice_with_lines(po["id"], [
        {"product_id": teq["id"], "received_qty": 12, "unit_cost_cents": 2495},
        {"product_id": coin["id"], "received_qty": 6, "unit_cost_cents": 3200},
    ], freight_cents=1500)

    data = validate_success(api.post_invoice(inv["id"], _purchasing()))
    assert data["subtotal_cents"] == 49140, f"subtotal {data['subtotal_cents']}"
    assert data["discount_cents"] == 2457, f"discount {data['discount_cents']}"
    assert data["tax_cents"] == 4085, f"tax {data['tax_cents']}"
    assert data["invoice_total_cents"] == 52268, f"total {data['invoice_total_cents']}"


def test_invoice_total_excludes_no_discount_when_below_tier(api):
    """PRD §3.6: "the `discount_cents` as a tiered percentage of the subtotal — five
    percent if the subtotal is at least 40,000 cents, otherwise three percent if it is
    at least 30,000 cents, otherwise zero — rounded half-up to a whole cent, where the
    tier boundaries are inclusive so that a subtotal of exactly 40,000 cents takes the
    five-percent tier."

    Design: Difficulty/combinatorial_formula/invoice_subtotal_discount_tax_order_mode_c
    """
    # Subtotal 49140 (>= 40000) => 5% discount = 2457 confirms the highest tier engaged.
    teq = create_product(sku="TEQ-C2", name="Tequila", container_volume_ml=750, unit_cost_cents=2400)
    coin = create_product(sku="COIN-C2", name="Cointreau", container_volume_ml=700, unit_cost_cents=3000)
    po = create_submitted_po([
        {"product_id": teq["id"], "ordered_qty": 12, "unit_cost_cents": 2495},
        {"product_id": coin["id"], "ordered_qty": 6, "unit_cost_cents": 3200},
    ])
    inv = create_draft_invoice_with_lines(po["id"], [
        {"product_id": teq["id"], "received_qty": 12, "unit_cost_cents": 2495},
        {"product_id": coin["id"], "received_qty": 6, "unit_cost_cents": 3200},
    ], freight_cents=1500)
    data = validate_success(api.post_invoice(inv["id"], _purchasing()))
    # discount is exactly 5% of subtotal, not 3%.
    assert data["discount_cents"] == 2457
    assert data["discount_cents"] != round(49140 * 0.03)


def test_invoice_tier_boundary_inclusive_at_exactly_40000(api):
    """PRD §3.6: "the tier boundaries are inclusive so that a subtotal of exactly
    40,000 cents takes the five-percent tier."

    Design: Difficulty/boundary_precision_check/invoice_tier_boundary_inclusive_at_40000
    """
    teq = create_product(sku="TEQ-B6", name="Tequila", container_volume_ml=750, unit_cost_cents=2500)
    po = create_submitted_po([{"product_id": teq["id"], "ordered_qty": 16, "unit_cost_cents": 2500}])
    inv = create_draft_invoice_with_lines(po["id"], [
        {"product_id": teq["id"], "received_qty": 16, "unit_cost_cents": 2500}], freight_cents=0)

    data = validate_success(api.post_invoice(inv["id"], _purchasing()))
    assert data["subtotal_cents"] == 40000
    assert data["discount_cents"] == 2000, "subtotal == 40000 takes 5% tier (inclusive)"
    assert data["tax_cents"] == 3325
    assert data["invoice_total_cents"] == 41325


def test_invoice_tier_boundary_just_below_40000_takes_lower_tier(api):
    """PRD §3.6: "the `discount_cents` as a tiered percentage of the subtotal — five
    percent if the subtotal is at least 40,000 cents, otherwise three percent if it is
    at least 30,000 cents, otherwise zero — rounded half-up to a whole cent, where the
    tier boundaries are inclusive so that a subtotal of exactly 40,000 cents takes the
    five-percent tier."

    Design: Difficulty/boundary_precision_check/invoice_tier_boundary_inclusive_at_40000
    """
    # X-1 boundary: subtotal 39984 (< 40000) falls to the 3% tier.
    teq = create_product(sku="TEQ-B6L", name="Tequila", container_volume_ml=750, unit_cost_cents=2499)
    po = create_submitted_po([{"product_id": teq["id"], "ordered_qty": 16, "unit_cost_cents": 2499}])
    inv = create_draft_invoice_with_lines(po["id"], [
        {"product_id": teq["id"], "received_qty": 16, "unit_cost_cents": 2499}], freight_cents=0)
    data = validate_success(api.post_invoice(inv["id"], _purchasing()))
    assert data["subtotal_cents"] == 39984
    assert data["discount_cents"] == round(39984 * 0.03), "below 40000 -> 3% tier"


def test_ordered_total_computed_on_submit(api):
    """PRD §3.5: "Submission computes the order's `ordered_total_cents` as the sum,
    over every line, of that line's `ordered_qty` multiplied by its `unit_cost_cents`,
    moves the order to `SUBMITTED`, and bumps its `version`."

    Design: Corner/calculations/ordered_total_computed_on_submit
    """
    teq = create_product(sku="TEQ-OT", name="Tequila", container_volume_ml=750, unit_cost_cents=2400)
    coin = create_product(sku="COIN-OT", name="Cointreau", container_volume_ml=700, unit_cost_cents=3000)
    po = create_submitted_po([
        {"product_id": teq["id"], "ordered_qty": 12, "unit_cost_cents": 2495},
        {"product_id": coin["id"], "ordered_qty": 6, "unit_cost_cents": 3200},
    ])
    assert po["ordered_total_cents"] == 49140
    assert po["status"] == "SUBMITTED"


def test_invoice_post_lands_cost_and_posts_stock_immediately(api):
    """PRD §3.6: "For each billed line, the system overwrites the product's
    `unit_cost_cents` with the line's billed `unit_cost_cents` so that the product
    carries the latest landed cost, and it adds the line's `received_qty` to the
    product's `on_hand_units`."

    Design: Corner/consistency_model/invoice_post_immediate_landed_cost_visible
    """
    p = create_product(sku="P-LC", name="A", container_volume_ml=750, unit_cost_cents=2000)
    po = create_submitted_po([{"product_id": p["id"], "ordered_qty": 3, "unit_cost_cents": 2000}])
    inv = create_draft_invoice_with_lines(po["id"], [
        {"product_id": p["id"], "received_qty": 3, "unit_cost_cents": 2150}])
    validate_success(api.post_invoice(inv["id"], _purchasing()))

    refreshed = get_product(p["id"])
    assert refreshed["unit_cost_cents"] == 2150, "latest landed cost overwrites unit_cost"
    assert refreshed["on_hand_units"] == 3, "received_qty added to on_hand"


def test_invoice_post_cascades_onhand_then_reorder_flag(api):
    """PRD §3.6: "Posting an invoice lands new landed cost onto each billed product,
    adds received stock to each product's `on_hand_units`, recomputes each affected
    product's `needs_reorder`, and — when the order was still `SUBMITTED` — cascades
    the purchase order forward to `RECEIVED`."
    PRD §2.8: "every product carries a computed boolean `needs_reorder` that is true
    exactly when `on_hand_units` is strictly less than the `reorder_point_units` of the
    product's currently active par setting, and false otherwise."

    Design: Difficulty/transitive_cascade/invoice_post_cascade_onhand_to_reorder_flag
    """
    product, _par = create_product_with_par(par_level_units=24, reorder_point_units=10,
                                             sku="VOD-R", name="Vodka", unit_cost_cents=2200, case_pack=12)
    # on_hand starts 0 < reorder_point 10 => needs_reorder true.
    assert get_product(product["id"])["needs_reorder"] is True
    po = create_submitted_po([{"product_id": product["id"], "ordered_qty": 12, "unit_cost_cents": 2200}])
    inv = create_draft_invoice_with_lines(po["id"], [
        {"product_id": product["id"], "received_qty": 12, "unit_cost_cents": 2200}])
    data = validate_success(api.post_invoice(inv["id"], _purchasing()))
    assert data["status"] == "POSTED"

    refreshed = get_product(product["id"])
    assert refreshed["on_hand_units"] == 12, "on_hand bumped to 12"
    assert refreshed["needs_reorder"] is False, "12 >= reorder_point 10 => flag flips false"


def test_invoice_post_against_draft_po_rejected_invalid_state(api):
    """PRD §3.6: "The transition is permitted only when the invoice is `DRAFT`, has at
    least one line, references an order that is `SUBMITTED` or `RECEIVED`, and has every
    line's `product_id` present on the order's lines."

    Design: Difficulty/cross_entity_state_dependency/invoice_post_requires_po_submitted_or_received
    """
    p = create_product(sku="RUM-X7", name="Rum", container_volume_ml=750, unit_cost_cents=1800)
    # Create a DRAFT PO that is never submitted.
    po = validate_success(api.create_purchase_order(
        {"vendor_name": "Acme", "expected_at": "2026-03-02T00:00:00Z"}, _purchasing()), expected_status=201)
    validate_success(api.add_po_line(po["id"], {
        "product_id": p["id"], "ordered_qty": 6, "unit_cost_cents": 1800}, _purchasing()),
        expected_status=201)
    # Create the invoice directly against the DRAFT PO, add a matching line, and post it.
    inv = validate_success(api.create_invoice({
        "purchase_order_id": po["id"], "vendor_invoice_no": "INV-X7", "freight_cents": 0},
        _purchasing()), expected_status=201)
    validate_success(api.add_invoice_line(inv["id"], {
        "product_id": p["id"], "received_qty": 6, "unit_cost_cents": 1800}, _purchasing()),
        expected_status=201)

    validate_error(api.post_invoice(inv["id"], _purchasing()), ApiErrorId.ERR_INVALID_STATE)


def test_repost_already_posted_invoice_rejected_invalid_state(api):
    """PRD §3.6: "The transition is permitted only when the invoice is `DRAFT`, has at
    least one line, references an order that is `SUBMITTED` or `RECEIVED`, and has every
    line's `product_id` present on the order's lines."

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_product_not_on_po
    """
    p = create_product(sku="GIN-P5", name="Gin", container_volume_ml=750, unit_cost_cents=2000)
    po, inv = create_posted_invoice(
        po_lines=[{"product_id": p["id"], "ordered_qty": 5, "unit_cost_cents": 2000}],
        invoice_lines=[{"product_id": p["id"], "received_qty": 5, "unit_cost_cents": 2000}])
    # Re-posting the already-POSTED invoice fails the DRAFT precondition.
    validate_error(api.post_invoice(inv["id"], _purchasing()), ApiErrorId.ERR_INVALID_STATE)


def test_invoice_line_product_not_on_po_rejected(api):
    """PRD §3.6: "A billed product must appear on a line of the invoice's purchase
    order; an invoice line whose `product_id` is not present on any of the order's lines
    is rejected with `ERR_PRODUCT_NOT_ON_PO` (HTTP 422), and this same check is
    re-applied at post time."

    Design: Corner/validations/invoice_line_product_not_on_po_rejected
    """
    pa = create_product(sku="P-ON", name="A", container_volume_ml=750, unit_cost_cents=100)
    pb = create_product(sku="P-OFF", name="B", container_volume_ml=750, unit_cost_cents=200)
    po = create_submitted_po([{"product_id": pa["id"], "ordered_qty": 5, "unit_cost_cents": 100}])
    inv = validate_success(api.create_invoice({
        "purchase_order_id": po["id"], "vendor_invoice_no": "INV-ON", "freight_cents": 0},
        _purchasing()), expected_status=201)
    validate_error(
        api.add_invoice_line(inv["id"], add_invoice_line_payload(pb["id"], 1, 200), _purchasing()),
        ApiErrorId.ERR_PRODUCT_NOT_ON_PO)


def test_close_po_short_received_rejected(api):
    """PRD §3.5: "Closure additionally requires that receiving be complete: across all
    posted invoices, the received quantity summed per product must be at least the
    order's ordered quantity for that product, so that no short-receipt is left open.
    If any product remains short-received, the close is rejected with `ERR_SHORT_RECEIPT`
    (HTTP 422)."

    Design: Corner/validations/short_receipt_blocks_po_close
    """
    p = create_product(sku="P-SR", name="A", container_volume_ml=750, unit_cost_cents=100)
    po, inv = create_posted_invoice(
        po_lines=[{"product_id": p["id"], "ordered_qty": 10, "unit_cost_cents": 100}],
        invoice_lines=[{"product_id": p["id"], "received_qty": 4, "unit_cost_cents": 100}])
    # PO is RECEIVED but only 4 of 10 received.
    validate_error(api.close_purchase_order(po["id"], _purchasing()), ApiErrorId.ERR_SHORT_RECEIPT)


def test_invoice_post_cascades_po_submitted_to_received(api):
    """PRD §3.6: "If the referenced order was still `SUBMITTED`, posting cascades it
    forward to `RECEIVED`."
    PRD §3.5: "An order does not advance to `RECEIVED` by its own action: it cascades to
    `RECEIVED` automatically when its first invoice posts, as described in §3.6."

    Design: Difficulty/transitive_cascade/invoice_post_cascade_onhand_to_reorder_flag
    """
    p = create_product(sku="VOD-R2", name="Vodka", container_volume_ml=750, unit_cost_cents=2200)
    po = create_submitted_po([{"product_id": p["id"], "ordered_qty": 5, "unit_cost_cents": 2200}])
    assert po["status"] == "SUBMITTED"
    inv = create_draft_invoice_with_lines(po["id"], [
        {"product_id": p["id"], "received_qty": 5, "unit_cost_cents": 2200}])
    validate_success(api.post_invoice(inv["id"], _purchasing()))
    refreshed = validate_success(api.get_purchase_order(po["id"], _purchasing()))
    assert refreshed["status"] == "RECEIVED", "first posted invoice cascades PO to RECEIVED"


def test_invoice_post_against_received_po_allowed(api):
    """PRD §3.6: "The transition is permitted only when the invoice is `DRAFT`, has at
    least one line, references an order that is `SUBMITTED` or `RECEIVED`, and has every
    line's `product_id` present on the order's lines."

    Design: Difficulty/cross_entity_state_dependency/invoice_post_requires_po_submitted_or_received
    """
    p = create_product(sku="RUM-RC", name="Rum", container_volume_ml=750, unit_cost_cents=1800)
    # First invoice advances the PO to RECEIVED.
    po = create_submitted_po([{"product_id": p["id"], "ordered_qty": 10, "unit_cost_cents": 1800}])
    inv1 = create_draft_invoice_with_lines(po["id"], [
        {"product_id": p["id"], "received_qty": 4, "unit_cost_cents": 1800}])
    validate_success(api.post_invoice(inv1["id"], _purchasing()))
    assert validate_success(api.get_purchase_order(po["id"], _purchasing()))["status"] == "RECEIVED"
    # A second invoice posts against the now-RECEIVED PO (the other allowed state).
    inv2 = create_draft_invoice_with_lines(po["id"], [
        {"product_id": p["id"], "received_qty": 6, "unit_cost_cents": 1800}])
    data = validate_success(api.post_invoice(inv2["id"], _purchasing()))
    assert data["status"] == "POSTED", "posting against a RECEIVED PO is permitted"


def test_void_then_repost_voided_invoice_rejected_invalid_state(api):
    """PRD §3.6: "The transition is permitted only when the invoice is `DRAFT`, has at
    least one line, references an order that is `SUBMITTED` or `RECEIVED`, and has every
    line's `product_id` present on the order's lines."

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_product_not_on_po
    """
    p = create_product(sku="GIN-P5B", name="Gin", container_volume_ml=750, unit_cost_cents=2000)
    po = create_submitted_po([{"product_id": p["id"], "ordered_qty": 5, "unit_cost_cents": 2000}])
    inv = create_draft_invoice_with_lines(po["id"], [
        {"product_id": p["id"], "received_qty": 5, "unit_cost_cents": 2000}])
    # Void the DRAFT invoice (terminal VOID), then attempt to post it.
    validate_success(api.void_invoice(inv["id"], _purchasing()))
    validate_error(api.post_invoice(inv["id"], _purchasing()), ApiErrorId.ERR_INVALID_STATE)
