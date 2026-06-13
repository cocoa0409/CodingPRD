"""3-way match evaluation and vendor probation recompute (PRD §3.6, §3.7)."""
from db import db
from services.common import touch
from services.calculations import (
    floor_pct_ceiling, PRICE_TOLERANCE_PCT, AMOUNT_TOLERANCE_PCT,
    VENDOR_PROBATION_THRESHOLD,
)


def evaluate_match(invoice, po, receipt):
    """Run the 3-way match gates.

    Returns (passed, reason, detail). reason/detail are None when passed.
    Gate priority (first failing gate sets reason):
      NO_RECEIPT > PRICE_OVER_TOLERANCE > QTY_OVER_TOLERANCE > AMOUNT_OVER_TOLERANCE
    Per-line gates evaluated in ascending sku order.
    """
    # NO_RECEIPT is handled by the caller (a POSTED receipt must exist);
    # this function assumes receipt is a POSTED GoodsReceipt.
    po_price_by_sku = {}
    if po.get("lines"):
        for l in po["lines"]:
            po_price_by_sku[l["sku"]] = l["unit_price_cents"]

    received_by_sku = {}
    for rl in receipt["received_lines"]:
        received_by_sku[rl["sku"]] = received_by_sku.get(rl["sku"], 0) + rl["received_qty"]

    inv_lines = sorted(invoice["lines"], key=lambda l: l["sku"])

    # Price gate (ascending sku).
    for line in inv_lines:
        sku = line["sku"]
        po_price = po_price_by_sku.get(sku)
        if po_price is None:
            # No ordered price for this sku — treat as a price breach.
            return (False, "PRICE_OVER_TOLERANCE",
                    "sku %s has no purchase-order price" % sku)
        ceiling = floor_pct_ceiling(po_price, PRICE_TOLERANCE_PCT)
        if line["billed_unit_price_cents"] > ceiling:
            return (False, "PRICE_OVER_TOLERANCE",
                    "sku %s billed %d exceeds price ceiling %d" % (
                        sku, line["billed_unit_price_cents"], ceiling))

    # Quantity gate (ascending sku) — billed_qty must be <= received_qty.
    for line in inv_lines:
        sku = line["sku"]
        received_qty = received_by_sku.get(sku, 0)
        if line["billed_qty"] > received_qty:
            return (False, "QTY_OVER_TOLERANCE",
                    "sku %s billed_qty %d exceeds received %d" % (
                        sku, line["billed_qty"], received_qty))

    # Amount gate (invoice-wide).
    po_matched_amount = 0
    for sku, received_qty in received_by_sku.items():
        po_price = po_price_by_sku.get(sku)
        if po_price is not None:
            po_matched_amount += received_qty * po_price
    amount_ceiling = floor_pct_ceiling(po_matched_amount, AMOUNT_TOLERANCE_PCT)
    if invoice["invoice_total_cents"] > amount_ceiling:
        return (False, "AMOUNT_OVER_TOLERANCE",
                "invoice total %d exceeds amount ceiling %d" % (
                    invoice["invoice_total_cents"], amount_ceiling))

    return (True, None, None)


def open_exception_count(vendor_id):
    return sum(
        1 for ex in db.match_exceptions.values()
        if ex["vendor_id"] == vendor_id and ex["status"] == "OPEN"
    )


def recompute_vendor_status(vendor):
    """Recompute exception_count and apply automatic PROBATION transitions."""
    count = open_exception_count(vendor["id"])
    vendor["exception_count"] = count
    if vendor["status"] == "APPROVED" and count > VENDOR_PROBATION_THRESHOLD:
        vendor["status"] = "PROBATION"
    elif vendor["status"] == "PROBATION" and count <= VENDOR_PROBATION_THRESHOLD:
        vendor["status"] = "APPROVED"
    touch(vendor)
