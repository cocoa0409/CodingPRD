"""Vendor scorecard computations (PRD §3.8)."""
from datetime import timedelta

from db import db
from services.common import parse_instant
from services.calculations import (
    round_half_up, W_ON_TIME, W_PRICE, W_RELIABILITY,
)


def _po_issue_dt(po):
    """Purchase order issuance date = created_at instant."""
    return parse_instant(po["created_at"], "created_at")


def _promised_lead_days_for(po, sku):
    """Look up promised_lead_days from the awarded quote line for a sku."""
    quote_id = po.get("source_quote_id")
    if quote_id is None:
        return None
    quote = db.quotes.get(quote_id)
    if quote is None:
        return None
    for up in quote.get("unit_prices", []):
        if up["sku"] == sku:
            return up.get("promised_lead_days")
    return None


def _receipt_promised_date(po, receipt):
    """Promised date = po issuance date + max promised_lead_days over the
    receipt's skus (whichever applies). Returns a datetime or None."""
    issue_dt = _po_issue_dt(po)
    lead = None
    for rl in receipt["received_lines"]:
        d = _promised_lead_days_for(po, rl["sku"])
        if d is not None:
            lead = d if lead is None else max(lead, d)
    if lead is None:
        lead = 0
    return issue_dt + timedelta(days=lead)


def compute_scorecard(vendor, period_start_dt, period_end_dt, on_time_variant):
    """Compute on_time_rate_pct, price_compliance_pct, exception_pct,
    composite_score over POSTED receipts in [period_start, period_end)."""
    vendor_id = vendor["id"]
    grace_days = vendor.get("grace_days", 0)

    # POSTED receipts for this vendor's POs, received_at in the window.
    receipts = []
    for gr in db.goods_receipts.values():
        if gr["status"] != "POSTED":
            continue
        po = db.purchase_orders.get(gr["purchase_order_id"])
        if po is None or po["vendor_id"] != vendor_id:
            continue
        received_dt = parse_instant(gr["received_at"], "received_at")
        if period_start_dt <= received_dt < period_end_dt:
            receipts.append((gr, po, received_dt))

    total_count = len(receipts)

    # On-time rate.
    if total_count == 0:
        on_time_rate = 100
    else:
        on_time_count = 0
        for gr, po, received_dt in receipts:
            promised = _receipt_promised_date(po, gr)
            limit = promised
            if on_time_variant == "GRACE":
                limit = promised + timedelta(days=grace_days)
            if received_dt <= limit:
                on_time_count += 1
        on_time_rate = round_half_up(100 * on_time_count / total_count)

    # Exception percentage: percent of period receipts that produced an exception.
    if total_count == 0:
        exception_pct = 0
    else:
        receipt_ids = {gr["id"] for gr, _, _ in receipts}
        exc_receipt_ids = set()
        for ex in db.match_exceptions.values():
            if ex["vendor_id"] != vendor_id:
                continue
            invoice = db.invoices.get(ex["invoice_id"])
            if invoice is None:
                continue
            if invoice["goods_receipt_id"] in receipt_ids:
                exc_receipt_ids.add(invoice["goods_receipt_id"])
        exception_pct = round_half_up(100 * len(exc_receipt_ids) / total_count)

    # Price compliance: percent of matched invoice lines within price tolerance
    # over the period (invoices whose receipt is in the period window).
    receipt_ids = {gr["id"] for gr, _, _ in receipts}
    matched_lines = 0
    compliant_lines = 0
    for inv in db.invoices.values():
        if inv["vendor_id"] != vendor_id:
            continue
        if inv["goods_receipt_id"] not in receipt_ids:
            continue
        if inv["match_status"] != "MATCHED":
            continue
        po = db.purchase_orders.get(inv["purchase_order_id"])
        po_price_by_sku = {}
        if po is not None and po.get("lines"):
            po_price_by_sku = {l["sku"]: l["unit_price_cents"] for l in po["lines"]}
        from services.calculations import floor_pct_ceiling, PRICE_TOLERANCE_PCT
        for line in inv["lines"]:
            matched_lines += 1
            po_price = po_price_by_sku.get(line["sku"])
            if po_price is None:
                continue
            ceiling = floor_pct_ceiling(po_price, PRICE_TOLERANCE_PCT)
            if line["billed_unit_price_cents"] <= ceiling:
                compliant_lines += 1
    if matched_lines == 0:
        price_compliance_pct = 100
    else:
        price_compliance_pct = round_half_up(100 * compliant_lines / matched_lines)

    # Composite: round-each-then-sum.
    c1 = round_half_up(on_time_rate * W_ON_TIME)
    c2 = round_half_up(price_compliance_pct * W_PRICE)
    c3 = round_half_up((100 - exception_pct) * W_RELIABILITY)
    composite = c1 + c2 + c3

    return {
        "on_time_rate_pct": on_time_rate,
        "price_compliance_pct": price_compliance_pct,
        "exception_pct": exception_pct,
        "composite_score": composite,
    }
