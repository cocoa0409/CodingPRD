"""Calculation rules (PRD 3.2, 3.4, 3.7, 3.10, 3.12; SCAFFOLD calculations table)."""

import math
from decimal import Decimal

from common import round_half_up
from db import db, parse_iso

# ----- constants (from SCAFFOLD calculations table) -----
BASE_LABOR_RATE_CENTS = 12500
TIER1_HOURS = Decimal("2.0")
TIER2_HOURS = Decimal("6.0")
TIER2_DISCOUNT_CENTS = 1000
TIER3_DISCOUNT_CENTS = 2500
WARRANTY_LABOR_RATE_CENTS = 9000
SHOP_SUPPLY_BPS = 800
SHOP_SUPPLY_CAP_CENTS = 5000

WINTERIZATION_FEE_CENTS = 14900

CURTAILMENT_PCT_BPS = 1000
CURTAILMENT_DUE_DAYS = 90

DAYS_PER_YEAR = 365


# ---------------------------------------------------------------------------
# Deal pricing (PRD 3.4)
# ---------------------------------------------------------------------------
def trade_equity(deal, trade, variant):
    """trade_allowance_cents = appraised_value - payoff. May be negative.

    provisional -> payoff = TradeIn.estimated_payoff_cents
    final       -> payoff = Deal.approved_lender_payoff_cents
    No trade -> 0.
    """
    if trade is None:
        return 0
    if variant == "final":
        payoff = deal.get("approved_lender_payoff_cents", 0)
    else:
        payoff = trade.get("estimated_payoff_cents", 0)
    return trade["appraised_value_cents"] - payoff


def out_the_door(deal, trade_allowance_cents):
    """Two independently taxable lines, doc fee non-taxable. Per-line tax rounding."""
    sale_price = deal["sale_price_cents"]
    freight = deal.get("freight_setup_cents", 0)
    doc_fee = deal.get("doc_fee_cents", 39900)
    tax_rate_bps = deal["tax_rate_bps"]

    taxable_sale = max(sale_price - max(trade_allowance_cents, 0), 0)
    taxable_freight = freight

    tax_sale = round_half_up(Decimal(taxable_sale) * Decimal(tax_rate_bps) / Decimal(10000))
    tax_freight = round_half_up(Decimal(taxable_freight) * Decimal(tax_rate_bps) / Decimal(10000))

    return sale_price + freight + tax_sale + tax_freight + doc_fee


def amount_financed(otd_cents, deal, trade_allowance_cents):
    down = deal.get("down_payment_cents", 0)
    financed = otd_cents - down - max(trade_allowance_cents, 0)
    return max(financed, 0)


def compute_deal_pricing(deal, trade, variant):
    """Return (trade_allowance, out_the_door, amount_financed) for a variant."""
    ta = trade_equity(deal, trade, variant)
    otd = out_the_door(deal, ta)
    fin = amount_financed(otd, deal, ta)
    return ta, otd, fin


# ---------------------------------------------------------------------------
# Repair order labor / shop supplies (PRD 3.7)
# ---------------------------------------------------------------------------
def ro_service_lines(ro_id):
    lines = [sl for sl in db.service_lines.values() if sl["repair_order_id"] == ro_id]
    return sorted(lines, key=lambda l: (l.get("created_at", ""), l.get("_seq", 0)))


def effective_labor_rate(total_flat_hours, is_warranty):
    if is_warranty:
        return WARRANTY_LABOR_RATE_CENTS
    h = Decimal(str(total_flat_hours))
    if h <= TIER1_HOURS:
        return BASE_LABOR_RATE_CENTS
    elif h <= TIER2_HOURS:
        return BASE_LABOR_RATE_CENTS - TIER2_DISCOUNT_CENTS
    else:
        return BASE_LABOR_RATE_CENTS - TIER3_DISCOUNT_CENTS


def line_extended_labor(flat_rate_hours, rate_cents):
    return round_half_up(Decimal(str(flat_rate_hours)) * Decimal(rate_cents))


def ro_labor_total(ro):
    """Finalize labor_total and shop_supplies for a repair order."""
    lines = ro_service_lines(ro["id"])
    total_flat_hours = sum(Decimal(str(l["flat_rate_hours"])) for l in lines) if lines else Decimal(0)
    is_warranty = ro.get("is_warranty", False)
    rate = effective_labor_rate(total_flat_hours, is_warranty)

    labor_total = 0
    for l in lines:
        labor_total += line_extended_labor(l["flat_rate_hours"], rate)

    if is_warranty:
        shop_supplies = 0
    else:
        raw = round_half_up(Decimal(labor_total) * Decimal(SHOP_SUPPLY_BPS) / Decimal(10000))
        shop_supplies = min(raw, SHOP_SUPPLY_CAP_CENTS)

    return labor_total, shop_supplies


def ro_parts_total(ro_id):
    """Sum extended_cents of CONSUMED part lines on the order."""
    total = 0
    for pl in db.part_lines.values():
        if pl["repair_order_id"] == ro_id and pl["status"] == "CONSUMED":
            total += pl["extended_cents"]
    return total


# ---------------------------------------------------------------------------
# Floor-plan interest (PRD 3.2)
# ---------------------------------------------------------------------------
def elapsed_days(opened_on_iso):
    opened = parse_iso(opened_on_iso)
    if opened is None:
        return 0
    delta = (db.clock - opened).total_seconds()
    if delta < 0:
        return 0
    return int(math.floor(delta / 86400))


def per_diem(principal_cents, apr_bps):
    return round_half_up(
        Decimal(principal_cents) * Decimal(apr_bps) / Decimal(10000) / Decimal(DAYS_PER_YEAR)
    )


def simple_interest(loan):
    days = elapsed_days(loan["opened_on"])
    pd = per_diem(loan["original_advance_cents"], loan["apr_bps"])
    return pd * days


def loan_curtailments(loan_id):
    cs = [c for c in db.curtailments.values() if c["floor_plan_loan_id"] == loan_id]
    # created_at ASC; ties broken by created_at then lower principal_cents
    return sorted(
        cs,
        key=lambda c: (c.get("created_at", ""), c.get("_seq", 0), c.get("principal_cents", 0)),
    )


def declining_interest(loan):
    """Walk POSTED curtailments in created_at ASC, accrue per-diem on the
    outstanding principal within each inter-curtailment segment."""
    total_days = elapsed_days(loan["opened_on"])
    if total_days <= 0:
        return 0
    apr_bps = loan["apr_bps"]
    opened = parse_iso(loan["opened_on"])
    curtailments = loan_curtailments(loan["id"])

    # Build segment boundaries by elapsed-day position of each curtailment.
    # Each segment runs from the previous boundary day to the next, accruing on
    # the principal outstanding during that segment.
    principal = loan["original_advance_cents"]
    prev_day = 0
    interest = 0
    for c in curtailments:
        c_time = parse_iso(c["created_at"])
        if c_time is None or opened is None:
            c_day = total_days
        else:
            c_day = int(math.floor((c_time - opened).total_seconds() / 86400))
        if c_day < 0:
            c_day = 0
        if c_day > total_days:
            c_day = total_days
        seg_days = c_day - prev_day
        if seg_days > 0:
            interest += per_diem(principal, apr_bps) * seg_days
        principal = max(principal - c["principal_cents"], 0)
        prev_day = c_day

    # final segment to current clock
    seg_days = total_days - prev_day
    if seg_days > 0:
        interest += per_diem(principal, apr_bps) * seg_days
    return interest


def accrued_interest(loan, basis):
    if basis == "DECLINING":
        return declining_interest(loan)
    return simple_interest(loan)


# ---------------------------------------------------------------------------
# Storage fee (PRD 3.10)
# ---------------------------------------------------------------------------
def storage_fee(agreement):
    start = parse_iso(agreement["period_start"])
    end = parse_iso(agreement["period_end"])
    seconds = (end - start).total_seconds()
    span_days = int(math.ceil(seconds / 86400))
    months = int(math.ceil(span_days / 30)) if span_days > 0 else 0
    if months < 1:
        months = 1
    base = months * agreement["monthly_rate_cents"]
    if agreement.get("includes_winterization", False):
        return base + WINTERIZATION_FEE_CENTS
    return base


# ---------------------------------------------------------------------------
# Warranty claim amount (PRD 3.12)
# ---------------------------------------------------------------------------
def warranty_claim_amount(claim):
    ro_id = claim.get("repair_order_id")
    if not ro_id:
        return 0
    ro = db.repair_orders.get(ro_id)
    if ro is None:
        return 0
    labor = ro.get("labor_total_cents", 0) or 0
    parts = ro.get("parts_total_cents", 0) or 0
    if claim["kind"] == "RECALL":
        return labor
    return labor + parts


# ---------------------------------------------------------------------------
# Required scheduled curtailment (PRD 3.2)
# ---------------------------------------------------------------------------
def required_scheduled_curtailment(loan):
    return round_half_up(
        Decimal(loan["original_advance_cents"]) * Decimal(CURTAILMENT_PCT_BPS) / Decimal(10000)
    )
