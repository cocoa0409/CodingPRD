"""Purchase-order state machine, invoice void compensation, and the
conserved-quantity invariants of post/void and submit/cancel.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_product, create_submitted_po, create_draft_invoice_with_lines,
    create_posted_invoice, get_product,
    PURCHASING_AGENT,
)


def test_invoice_post_then_void_compensation_branch(api):
    """PRD §3.6: "Voiding a `POSTED` invoice — permitted only while the referenced order
    is not yet `CLOSED` — runs the mirror compensation: for each line it subtracts the
    line's `received_qty` back out of the product's `on_hand_units`, recomputes each
    affected product's `needs_reorder`, and, if this was the only posted invoice on the
    order, reverts the order from `RECEIVED` back to `SUBMITTED`; the invoice then moves
    to `VOID` and its `version` is bumped."

    Design: Difficulty/non_linear_state_machine/invoice_post_then_void_compensation_branch
    """
    gin = create_product(sku="GIN-V", name="Gin", container_volume_ml=750, unit_cost_cents=2000)
    po, inv = create_posted_invoice(
        po_lines=[{"product_id": gin["id"], "ordered_qty": 10, "unit_cost_cents": 2000}],
        invoice_lines=[{"product_id": gin["id"], "received_qty": 10, "unit_cost_cents": 2000}])
    assert get_product(gin["id"])["on_hand_units"] == 10

    data = validate_success(api.void_invoice(inv["id"], PURCHASING_AGENT))
    assert data["status"] == "VOID"
    assert get_product(gin["id"])["on_hand_units"] == 0, "void reverses received stock"
    refreshed_po = validate_success(api.get_purchase_order(po["id"], PURCHASING_AGENT))
    assert refreshed_po["status"] == "SUBMITTED", "sole posted invoice void reverts PO to SUBMITTED"


def test_invoice_void_conserves_product_on_hand(api):
    """PRD §2.9: "Posting an invoice lands new landed cost onto each billed product, adds
    received stock to each product's `on_hand_units` ... Voiding a posted invoice runs the
    mirror-image compensation: it reverses the received stock out of each product's
    `on_hand_units`, recomputes `needs_reorder`."

    Design: Difficulty/compensating_invariant/invoice_void_conserves_product_on_hand
    """
    gin = create_product(sku="GIN-I9", name="Gin", container_volume_ml=750, unit_cost_cents=2000)
    on_hand_before = get_product(gin["id"])["on_hand_units"]
    assert on_hand_before == 0
    po, inv = create_posted_invoice(
        po_lines=[{"product_id": gin["id"], "ordered_qty": 7, "unit_cost_cents": 2000}],
        invoice_lines=[{"product_id": gin["id"], "received_qty": 7, "unit_cost_cents": 2000}])
    assert get_product(gin["id"])["on_hand_units"] == 7

    data = validate_success(api.void_invoice(inv["id"], PURCHASING_AGENT))
    assert data["status"] == "VOID"
    assert get_product(gin["id"])["on_hand_units"] == on_hand_before, \
        "on_hand after void equals on_hand before post (the void exactly cancels the post)"


def test_po_cancel_with_no_invoice_conserves_stock_basis(api):
    """PRD §3.5: "An order may instead be cancelled. Cancellation from `DRAFT` is always
    permitted. Cancellation from `SUBMITTED` is permitted only when no posted invoice
    references the order; if a posted invoice exists, the cancel is blocked as an invalid
    state transition. Cancellation moves the order to the terminal `CANCELLED` state and
    bumps its `version`."
    PRD §2.8: A product's `on_hand_units` "begins at 0 when a product is created and is
    mutated only by the postings described in §3 — invoice posting, count finalization,
    and waste logging."

    Design: Difficulty/compensating_invariant/po_cancel_conserves_ordered_total_zero_basis
    """
    rum = create_product(sku="RUM-I9", name="Rum", container_volume_ml=750, unit_cost_cents=1800)
    assert get_product(rum["id"])["on_hand_units"] == 0
    po = create_submitted_po([{"product_id": rum["id"], "ordered_qty": 9, "unit_cost_cents": 1800}])

    data = validate_success(api.cancel_purchase_order(po["id"], PURCHASING_AGENT))
    assert data["status"] == "CANCELLED"
    assert get_product(rum["id"])["on_hand_units"] == 0, \
        "cancel with no receipts injects no stock; on_hand stays at its pre-PO value"


def test_submit_already_submitted_po_rejected(api):
    """PRD §3.5: "Submitting an order is allowed only when it is `DRAFT`, carries at least
    one line, and every line's product is `ACTIVE`; otherwise the transition is rejected
    with `ERR_INVALID_STATE` (HTTP 409) for a wrong-state order."

    Design: Corner/state_machines/submit_already_submitted_po_returns_invalid_state
    """
    p = create_product(sku="P-S1", name="A", container_volume_ml=750, unit_cost_cents=100)
    po = create_submitted_po([{"product_id": p["id"], "ordered_qty": 1, "unit_cost_cents": 100}])
    validate_error(api.submit_purchase_order(po["id"], PURCHASING_AGENT), ApiErrorId.ERR_INVALID_STATE)


def test_submit_po_with_no_lines_rejected(api):
    """PRD §3.5: "Submitting an order is allowed only when it is `DRAFT`, carries at least
    one line, and every line's product is `ACTIVE`; otherwise the transition is rejected
    with `ERR_INVALID_STATE` (HTTP 409) for a wrong-state order."

    Design: Corner/state_machines/submit_po_with_no_lines_rejected
    """
    po = validate_success(api.create_purchase_order(
        {"vendor_name": "Acme", "expected_at": "2026-03-02T00:00:00Z"}, PURCHASING_AGENT),
        expected_status=201)
    validate_error(api.submit_purchase_order(po["id"], PURCHASING_AGENT), ApiErrorId.ERR_INVALID_STATE)


def test_cancel_received_po_rejected(api):
    """PRD §3.5: "An order may instead be cancelled. Cancellation from `DRAFT` is always
    permitted. Cancellation from `SUBMITTED` is permitted only when no posted invoice
    references the order; if a posted invoice exists, the cancel is blocked as an invalid
    state transition."

    Design: Corner/state_machines/cancel_received_po_rejected_invalid_state
    """
    p = create_product(sku="P-CR", name="A", container_volume_ml=750, unit_cost_cents=100)
    po, _inv = create_posted_invoice(
        po_lines=[{"product_id": p["id"], "ordered_qty": 4, "unit_cost_cents": 100}],
        invoice_lines=[{"product_id": p["id"], "received_qty": 4, "unit_cost_cents": 100}])
    # Posting advanced the PO to RECEIVED; cancel is not an allowed transition from RECEIVED.
    validate_error(api.cancel_purchase_order(po["id"], PURCHASING_AGENT), ApiErrorId.ERR_INVALID_STATE)


def test_void_posted_invoice_reverts_po_to_submitted(api):
    """PRD §3.6: "Voiding a `POSTED` invoice — permitted only while the referenced order
    is not yet `CLOSED` — runs the mirror compensation: ... and, if this was the only
    posted invoice on the order, reverts the order from `RECEIVED` back to `SUBMITTED`; the
    invoice then moves to `VOID` and its `version` is bumped."

    Design: Difficulty/non_linear_state_machine/invoice_post_then_void_compensation_branch
    """
    p = create_product(sku="GIN-V2", name="Gin", container_volume_ml=750, unit_cost_cents=2000)
    po, inv = create_posted_invoice(
        po_lines=[{"product_id": p["id"], "ordered_qty": 8, "unit_cost_cents": 2000}],
        invoice_lines=[{"product_id": p["id"], "received_qty": 8, "unit_cost_cents": 2000}])
    assert validate_success(api.get_purchase_order(po["id"], PURCHASING_AGENT))["status"] == "RECEIVED"
    validate_success(api.void_invoice(inv["id"], PURCHASING_AGENT))
    # The sole posted invoice's void reverts the order to SUBMITTED (the branch's PO effect).
    assert validate_success(api.get_purchase_order(po["id"], PURCHASING_AGENT))["status"] == "SUBMITTED"


def test_void_draft_invoice_has_no_stock_effect(api):
    """PRD §3.6: "Voiding a `DRAFT` invoice simply moves it to the terminal `VOID` state
    and bumps its `version`, with no stock or order effects."

    Design: Difficulty/compensating_invariant/invoice_void_conserves_product_on_hand
    """
    p = create_product(sku="GIN-I9B", name="Gin", container_volume_ml=750, unit_cost_cents=2000)
    po = create_submitted_po([{"product_id": p["id"], "ordered_qty": 7, "unit_cost_cents": 2000}])
    inv = create_draft_invoice_with_lines(po["id"], [
        {"product_id": p["id"], "received_qty": 7, "unit_cost_cents": 2000}])
    # DRAFT invoice never posted -> on_hand untouched at 0; voiding it changes nothing on stock.
    assert get_product(p["id"])["on_hand_units"] == 0
    data = validate_success(api.void_invoice(inv["id"], PURCHASING_AGENT))
    assert data["status"] == "VOID"
    assert get_product(p["id"])["on_hand_units"] == 0, "voiding a DRAFT invoice has no stock effect"


def test_po_cancel_from_submitted_moves_to_cancelled(api):
    """PRD §3.5: "Cancellation from `SUBMITTED` is permitted only when no posted invoice
    references the order ... Cancellation moves the order to the terminal `CANCELLED` state
    and bumps its `version`."

    Design: Difficulty/compensating_invariant/po_cancel_conserves_ordered_total_zero_basis
    """
    rum = create_product(sku="RUM-I9B", name="Rum", container_volume_ml=750, unit_cost_cents=1800)
    po = create_submitted_po([{"product_id": rum["id"], "ordered_qty": 9, "unit_cost_cents": 1800}])
    ordered_total = po["ordered_total_cents"]
    data = validate_success(api.cancel_purchase_order(po["id"], PURCHASING_AGENT))
    assert data["status"] == "CANCELLED"
    # The cancel injects no receipts; ordered_total is unchanged and the product stays at 0.
    assert data["ordered_total_cents"] == ordered_total
    assert get_product(rum["id"])["on_hand_units"] == 0
