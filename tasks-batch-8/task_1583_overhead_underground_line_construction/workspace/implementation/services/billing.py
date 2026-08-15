"""Billing and premium-pay calculations (scaffold Table 3; PRD 3.7 / 3.9).

billing_extension: tiered per-line pricing with a floored threshold, a
billable pool debited by this work package's frozen invoices, and per-component
HALF_UP rounding pinned before summation.
storm_premium_pay: pure_callout vs standby_convert variants.
"""
from decimal import Decimal

from db import db
from util import dec, round_money, floor_decimal, parse_date
from services.core import accepted_quantity


def _eligible_units(bid_item_id, period_start, period_end, variant):
    """SUM(quantity_reported) over the bid item's entries with work_date in
    [period_start, period_end] (inclusive); final counts ACCEPTED only,
    provisional counts SUBMITTED + ACCEPTED."""
    ps = parse_date(period_start)
    pe = parse_date(period_end)
    statuses = ("ACCEPTED",) if variant == "final" else ("SUBMITTED", "ACCEPTED")
    total = dec(0)
    for e in db["production_entries"].values():
        if e["bid_item_id"] != bid_item_id or e["status"] not in statuses:
            continue
        wd = parse_date(e["work_date"])
        if ps <= wd <= pe:
            total += dec(e["quantity_reported"])
    return total


def _already_billed(work_package_id, bid_item_id, exclude_invoice_id=None):
    """This bid item's units on lines of this work package's invoices standing
    in SUBMITTED / APPROVED / PAID."""
    total = dec(0)
    for inv in db["invoices"].values():
        if inv["work_package_id"] != work_package_id:
            continue
        if inv["status"] not in ("SUBMITTED", "APPROVED", "PAID"):
            continue
        if exclude_invoice_id is not None and inv["id"] == exclude_invoice_id:
            continue
        for line in inv.get("frozen_lines") or []:
            if line["bid_item_id"] == bid_item_id:
                total += dec(line["in_schedule_units"]) + dec(line["overrun_units"])
    return total


def compute_lines(work_package, period_start, period_end, variant="final"):
    """One line per bid item of the contract, in bid-item creation order.

    Returns (lines, subtotal, retainage_amount, amount_due) with exact Decimals
    internally; lines carry plain numbers for JSON output.
    """
    contract = db["contracts"].get(work_package["contract_id"])
    threshold_pct = contract["overrun_threshold_pct"]
    retainage_pct = contract["retainage_pct"]

    bid_items = [b for b in db["bid_items"].values()
                 if b["contract_id"] == contract["id"]]
    bid_items.sort(key=lambda b: (b["created_at"], b["id"]))

    lines = []
    subtotal = dec(0)
    for b in bid_items:
        eligible = _eligible_units(b["id"], period_start, period_end, variant)
        already = _already_billed(work_package["id"], b["id"])
        billable = eligible - already
        if billable < 0:
            billable = dec(0)
        # Tier positioning: cumulative accepted OUTSIDE this period.
        eligible_final = _eligible_units(b["id"], period_start, period_end, "final")
        prior_cumulative = accepted_quantity(b["id"]) - eligible_final
        threshold_units = dec(floor_decimal(dec(b["estimated_quantity"]) * dec(threshold_pct)))
        room = threshold_units - prior_cumulative
        in_schedule = billable if billable < room else room
        if in_schedule < 0:
            in_schedule = dec(0)
        overrun = billable - in_schedule
        overrun_rate_applied = b["overrun_rate"] if b.get("overrun_rate") is not None else b["unit_price"]
        ext = round_money(in_schedule * dec(b["unit_price"])) \
            + round_money(overrun * dec(overrun_rate_applied))
        subtotal += ext
        lines.append({
            "bid_item_id": b["id"],
            "item_code": b["item_code"],
            "in_schedule_units": _out(in_schedule),
            "overrun_units": _out(overrun),
            "in_schedule_rate": _out(dec(b["unit_price"])),
            "overrun_rate_applied": _out(dec(overrun_rate_applied)),
            "extension_amount": _out(ext),
        })

    retainage = round_money(subtotal * dec(retainage_pct))
    amount_due = subtotal - retainage
    return lines, subtotal, retainage, amount_due


def _out(d: Decimal):
    from util import num
    return num(d)


def totals_as_numbers(subtotal, retainage, amount_due):
    return _out(subtotal), _out(retainage), _out(amount_due)


def line_total_units(line):
    return dec(line["in_schedule_units"]) + dec(line["overrun_units"])


# ---------------------------------------------------------------------------
# Storm premium pay (PRD 3.7)
# ---------------------------------------------------------------------------

STANDBY_MULT = dec("0.5")
CALLOUT_MULT = dec("2.0")
CALLOUT_MINIMUM_HOURS = dec(4)


def compute_premium_pay(activation, crew):
    """Variant dispatch on the converted flag (PRD 3.7: 'the converted flag
    decides between them'). Each component rounded HALF_UP to 2 dp separately,
    then summed."""
    base = dec(crew["base_rate_per_hour"])
    hours_standby = dec(activation["hours_standby"])
    hours_worked = dec(activation["hours_worked"])
    if activation["converted"]:
        # standby_convert: standby at 0.5x, worked at 2.0x, no minimum.
        return round_money(hours_standby * STANDBY_MULT * base) \
            + round_money(hours_worked * CALLOUT_MULT * base)
    # pure_callout: max(hours_worked, 4) at 2.0x; standby hours not credited.
    credited = hours_worked if hours_worked > CALLOUT_MINIMUM_HOURS else CALLOUT_MINIMUM_HOURS
    return round_money(credited * CALLOUT_MULT * base)
