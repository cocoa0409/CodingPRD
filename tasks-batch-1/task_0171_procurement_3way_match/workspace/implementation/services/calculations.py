"""Calculation rules (PRD §2.8, §3): totals, approval matrix, 3-way match,
on-time rate, composite score. All money is integer cents; percentages use
round-half-up; tolerance ceilings use floor."""
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR


# Tolerance constants (PRD §3.6 / scaffold three_way_match).
PRICE_TOLERANCE_PCT = 5
QTY_TOLERANCE_PCT = 0
AMOUNT_TOLERANCE_PCT = 2

# Vendor probation threshold (PRD §2.9): probation once exception_count > 3.
VENDOR_PROBATION_THRESHOLD = 3

# Composite-score weights (PRD §3.8).
W_ON_TIME = Decimal("0.5")
W_PRICE = Decimal("0.3")
W_RELIABILITY = Decimal("0.2")


def round_half_up(value):
    """Round a numeric value to the nearest integer, halves away from zero."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def floor_pct_ceiling(base_cents, tolerance_pct):
    """floor(base * (1 + tolerance_pct/100)) in integer cents."""
    factor = (Decimal(100) + Decimal(tolerance_pct)) / Decimal(100)
    raw = Decimal(base_cents) * factor
    return int(raw.quantize(Decimal("1"), rounding=ROUND_FLOOR))


def estimated_total(lines):
    """Sum over lines of quantity * estimated_unit_price_cents (exact)."""
    return sum(l["quantity"] * l["estimated_unit_price_cents"] for l in lines)


def required_levels_for(base_cents, approval_threshold, director_threshold):
    """Approval matrix (PRD §3.1): strict-greater thresholds."""
    levels = 1
    if base_cents > approval_threshold:
        levels = 2
    if base_cents > director_threshold:
        levels = 3
    return levels


def quote_total(quote_unit_prices, requisition_qty_by_sku):
    """Sum over priced lines of unit_price_cents * requisition quantity."""
    total = 0
    for up in quote_unit_prices:
        sku = up["sku"]
        qty = requisition_qty_by_sku.get(sku, 0)
        total += up["unit_price_cents"] * qty
    return total


def invoice_total(lines):
    """Round each line's billed_qty * billed_unit_price_cents to whole cents,
    then sum (PRD §3.6). Inputs are integer cents so each product is already a
    whole cent; the per-line then-sum order is preserved."""
    total = 0
    for l in lines:
        total += l["billed_qty"] * l["billed_unit_price_cents"]
    return total


ROLE_FOR_LEVEL = {1: "MANAGER", 2: "DIRECTOR", 3: "CFO"}
