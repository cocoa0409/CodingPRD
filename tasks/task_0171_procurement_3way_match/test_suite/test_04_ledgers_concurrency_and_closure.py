"""Conserved-quantity invariants, optimistic concurrency on blanket draws, and
purchase-order/release closure guards.

Covers difficulty queue rule compensating_invariant, plus the corner
'cross_cutting_layers' OCC instance and the PO/release conditional-action
instances in the 'endpoints' section.
"""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, assert_po_line_received_total,
)
import test_helpers.fixtures as fx


# ===========================================================================
# RULE 9 — compensating_invariant
# ===========================================================================

def test_blanket_remaining_ceiling_conserved_on_release_create_then_cancel(api):
    """PRD §3.4: "On a successful create the release is born OPEN, the blanket's
    remaining_amount_cents is decremented by amount_cents, and the blanket's version is
    incremented by one"
    PRD §3.4: "Cancelling a release restores its amount_cents to the parent blanket's
    remaining_amount_cents and increments that blanket's version by one."

    Design: Difficulty/compensating_invariant/blanket_remaining_ceiling_conserved_on_release_create_then_cancel
    """
    vendor, category, po = fx.setup_blanket_po(tax_id="TAX-V-17", code="OFFICE17",
                                               ceiling_amount_cents=1000000)
    rel = fx.create_release(po["id"], 300000, po["version"],
                            lines=[{"sku": "A", "quantity": 3, "unit_price_cents": 100000}])
    po_after_draw = validate_success(api.get_purchase_order(po["id"], fx.BUYER_H), 200)
    assert po_after_draw["remaining_amount_cents"] == 700000

    cancelled = validate_success(api.cancel_release_order(rel["id"], fx.BUYER_H), 200)
    assert cancelled["status"] == "CANCELLED"
    po_final = validate_success(api.get_purchase_order(po["id"], fx.BUYER_H), 200)
    assert po_final["remaining_amount_cents"] == 1000000


def test_po_received_quantity_ledger_conserved_on_receipt_post_then_reverse(api):
    """PRD §3.5: "Posting a receipt increments each affected PO line's received_total by
    the received_qty for that sku."
    PRD §3.5: "Reversing decrements each affected PO line's received_total by that
    receipt's received_qty per sku, the compensating restore that keeps the quantity
    ledger conserved"

    Design: Difficulty/compensating_invariant/po_received_quantity_ledger_conserved_on_receipt_post_then_reverse
    """
    vendor, category, req, quote, po = fx.setup_standard_po(
        tax_id="TAX-V-18", code="OFFICE18",
        lines=[{"sku": "A", "description": "Rod", "quantity": 5, "estimated_unit_price_cents": 1000}],
    )
    receipt = fx.post_receipt(po["id"], [{"sku": "A", "received_qty": 2}])
    po_after_post = validate_success(api.get_purchase_order(po["id"], fx.BUYER_H), 200)
    assert_po_line_received_total(po_after_post, "A", 2)

    reversed_receipt = validate_success(api.reverse_goods_receipt(receipt["id"], fx.RECEIVER_H), 200)
    assert reversed_receipt["status"] == "REVERSED"
    po_final = validate_success(api.get_purchase_order(po["id"], fx.BUYER_H), 200)
    assert_po_line_received_total(po_final, "A", 0)


# ===========================================================================
# CORNER: cross_cutting_layers — OCC stale version
# ===========================================================================

def test_stale_blanket_version_on_release_returns_412(api):
    """PRD §2.7: "If expected_purchase_order_version does not equal the blanket purchase
    order's current version, the create is rejected with ERR_STALE_VERSION (HTTP 412)."
    PRD §3.4: "On a successful create the release is born OPEN, the blanket's
    remaining_amount_cents is decremented by amount_cents, and the blanket's version is
    incremented by one"

    Design: Corner/cross_cutting_layers/stale_blanket_version_release_returns_412_stale_version
    """
    vendor, category, po = fx.setup_blanket_po(tax_id="TAX-OCC1", code="OCC1CAT",
                                               ceiling_amount_cents=1000000)
    stale_version = po["version"]
    # First release succeeds and advances the blanket version (1 -> 2).
    fx.create_release(po["id"], 200000, stale_version,
                      lines=[{"sku": "A", "quantity": 2, "unit_price_cents": 100000}])
    po_after = validate_success(api.get_purchase_order(po["id"], fx.BUYER_H), 200)
    assert po_after["version"] == stale_version + 1

    # Second release still carrying the originally observed version is stale.
    res = api.create_release_order(
        {"blanket_po_id": po["id"], "amount_cents": 100000,
         "lines": [{"sku": "A", "quantity": 1, "unit_price_cents": 100000}],
         "expected_purchase_order_version": stale_version}, fx.BUYER_H)
    validate_error(res, "ERR_STALE_VERSION")

    po_final = validate_success(api.get_purchase_order(po["id"], fx.BUYER_H), 200)
    assert po_final["remaining_amount_cents"] == 800000


# ===========================================================================
# CORNER: endpoints — PO/release closure conditional actions
# ===========================================================================

def test_standard_po_close_before_full_receipt_returns_po_not_fully_received(api):
    """PRD §3.3: "For a STANDARD order, closing requires that every PO line's received_total
    has reached at least its ordered quantity, unless the buyer supplies a truthy force flag
    to override - without full receipt and without force the close is refused with
    ERR_PO_NOT_FULLY_RECEIVED."

    Design: Corner/endpoints/standard_po_close_before_full_receipt_returns_po_not_fully_received
    """
    vendor, category, req, quote, po, receipt = fx.setup_received_standard_po(
        tax_id="TAX-CL1", code="CL1CAT", quantity=2, unit_price_cents=1000, received_qty=1,
    )
    res = api.close_purchase_order(po["id"], {}, fx.BUYER_H)
    validate_error(res, "ERR_PO_NOT_FULLY_RECEIVED")
    after = validate_success(api.get_purchase_order(po["id"], fx.BUYER_H), 200)
    assert after["status"] == "ISSUED"


def test_close_blanket_po_with_open_release_returns_blanket_has_open_releases(api):
    """PRD §3.3: "For a BLANKET order, closing requires that no OPEN release remains
    against it, otherwise ERR_BLANKET_HAS_OPEN_RELEASES."

    Design: Corner/endpoints/close_blanket_po_with_open_release_returns_blanket_has_open_releases
    """
    vendor, category, po = fx.setup_blanket_po(tax_id="TAX-CL2", code="CL2CAT",
                                               ceiling_amount_cents=1000000)
    fx.create_release(po["id"], 200000, po["version"],
                      lines=[{"sku": "A", "quantity": 2, "unit_price_cents": 100000}])
    res = api.close_purchase_order(po["id"], {}, fx.BUYER_H)
    validate_error(res, "ERR_BLANKET_HAS_OPEN_RELEASES")


def test_cancel_po_with_posted_receipt_returns_po_has_receipts(api):
    """PRD §3.3: "Alternatively a buyer may cancel an ISSUED order, moving it to CANCELLED;
    cancellation is refused with ERR_PO_HAS_RECEIPTS if any POSTED goods receipt references
    the order."

    Design: Corner/endpoints/cancel_po_with_posted_receipt_returns_po_has_receipts
    """
    vendor, category, req, quote, po, receipt = fx.setup_received_standard_po(
        tax_id="TAX-CN1", code="CN1CAT", quantity=2, unit_price_cents=1000, received_qty=2,
    )
    res = api.cancel_purchase_order(po["id"], fx.BUYER_H)
    validate_error(res, "ERR_PO_HAS_RECEIPTS")


def test_cancel_release_with_posted_receipt_returns_release_has_receipts(api):
    """PRD §3.4: "A buyer may cancel an OPEN release, moving it from OPEN to CANCELLED; this
    is refused with ERR_RELEASE_HAS_RECEIPTS if any POSTED goods receipt references the
    release."

    Design: Corner/endpoints/cancel_release_with_posted_receipt_returns_release_has_receipts
    """
    fx.set_clock("2026-03-01T00:00:00Z")
    vendor, category, po = fx.setup_blanket_po(tax_id="TAX-RC1", code="RC1CAT",
                                               ceiling_amount_cents=1000000)
    rel = fx.create_release(po["id"], 200000, po["version"],
                            lines=[{"sku": "A", "quantity": 2, "unit_price_cents": 100000}])
    # Partial receipt: covers 1 of the release's 2 units, so the release does NOT
    # fully cover and stays OPEN (PRD §3.5 only flips OPEN->RECEIVED on full cover).
    # The OPEN release still has a POSTED receipt referencing it, so cancellation
    # must be refused with ERR_RELEASE_HAS_RECEIPTS (PRD §3.4).
    fx.post_receipt(po["id"], [{"sku": "A", "received_qty": 1}],
                    received_at="2026-03-02T00:00:00Z", release_order_id=rel["id"])
    res = api.cancel_release_order(rel["id"], fx.BUYER_H)
    validate_error(res, "ERR_RELEASE_HAS_RECEIPTS")
