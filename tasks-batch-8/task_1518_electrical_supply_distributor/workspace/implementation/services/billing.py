"""Billing calculations (SCAFFOLD §1.3 / PRD §3.3, §3.8).

billed_release_line_amount:
  base_unit = QuoteLine.unit_price_cents for (release.quote_id, line item).
  FIRM_PRICE: eff_unit = base_unit.
  ESCALATION: eff_unit = round_half_up(base_unit * capped index ratio, 4dp).
  EA:   line_amount = round_half_up(bill_qty * eff_unit, 0)
  FOOT: line_amount = round_half_up(bill_qty * eff_unit, 0) + cut_charge
        (cut charge applies when bill_qty < reel_length_ft).
Precision: per-line round half-up to integer cents, then sum (pinned order).
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

import db
from db import clock_month, sort_key

_CENT = Decimal("1")
_UNIT = Decimal("0.0001")


def latest_index_at_or_before(month: str):
    """Latest index reading whose month <= the given month; None if none."""
    best_month = None
    best_value = None
    for m, v in db.index_readings.items():
        if m <= month and (best_month is None or m > best_month):
            best_month, best_value = m, v
    return best_value


def escalation_ratio(job: dict, quote: dict, target_month: str) -> Decimal:
    """Index ratio for ESCALATION billing, clamped by escalation_cap_pct."""
    base_idx = quote["award_index_value"]
    if base_idx is None:
        return Decimal(1)
    cur_idx = latest_index_at_or_before(target_month)
    if cur_idx is None:
        cur_idx = base_idx
    ratio = cur_idx / base_idx
    cap = job["escalation_cap_pct"]
    if cap is not None:
        ratio = min(ratio, Decimal(1) + cap)
    return ratio


def effective_unit_price(job: dict, quote: dict, base_unit: Decimal, target_month: str) -> Decimal:
    if job["pricing_mode"] == "FIRM_PRICE":
        return base_unit
    ratio = escalation_ratio(job, quote, target_month)
    return (base_unit * ratio).quantize(_UNIT, rounding=ROUND_HALF_UP)


def find_quote_line(quote_id: str, catalog_item_id: str):
    """First (created_at ASC) quote line of the quote carrying the item."""
    cands = [
        l
        for l in db.quote_lines.values()
        if l["quote_id"] == quote_id and l["catalog_item_id"] == catalog_item_id
    ]
    cands.sort(key=sort_key)
    return cands[0] if cands else None


def line_amount(job: dict, quote: dict, item: dict, catalog_item_id: str, bill_qty: Decimal) -> int:
    """Per-line extension in integer cents for the given billed quantity."""
    ql = find_quote_line(quote["id"], catalog_item_id)
    base_unit = ql["unit_price_cents"]
    eff_unit = effective_unit_price(job, quote, base_unit, clock_month())
    amount = int((bill_qty * eff_unit).quantize(_CENT, rounding=ROUND_HALF_UP))
    if item["sell_uom"] == "FOOT" and bill_qty < item["reel_length_ft"]:
        amount += item["cut_charge_cents"]
    return amount
