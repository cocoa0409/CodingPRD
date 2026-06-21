"""Calculation rules (SCAFFOLD §1.3 / PRD §2.7, §3.3-§3.8).

All money uses Decimal with ROUND_HALF_UP at 2 dp. Customer-supplied rate
inputs (e.g. molding_rate_per_ui) retain their submitted precision.
"""
import math
from decimal import Decimal, ROUND_HALF_UP

# --- line_cost constants ---
MAT_RATE_PER_SQFT = Decimal("6.00")
GLASS_RATE = {"REGULAR": Decimal("4.00"), "CONSERVATION": Decimal("9.00"), "MUSEUM": Decimal("18.00")}
UI_TIER1 = Decimal("80")
OVERSIZE_TIER1 = Decimal("40.00")
UI_TIER2 = Decimal("120")
OVERSIZE_TIER2 = Decimal("95.00")
MOUNT_UPCHARGE = {
    "NONE": Decimal("0.00"),
    "PLAIN": Decimal("15.00"),
    "DRY_MOUNT": Decimal("35.00"),
    "CONSERVATION_HINGE": Decimal("55.00"),
}
CONSERVATION_MULT = Decimal("1.20")
LABOR_PER_LINE = Decimal("45.00")

# --- quote / final constants ---
RUSH_PCT = Decimal("0.15")

# --- deposit constants ---
FRAGILE_DEPOSIT_FLOOR_PCT = Decimal("0.50")
MIN_DEPOSIT = Decimal("25.00")

# --- turnaround constants ---
BASE_TURNAROUND_DAYS = 14
FRAGILE_EXTRA_DAYS = 5

# --- scoring constants ---
OPEN_WEIGHT = 5
READY_UNPAID_WEIGHT = 15
RISK_CEILING = 100
SEED_BASE = 50
ONTIME_DELTA = 10
ABANDON_DELTA = 20
SCORE_FLOOR = 0
SCORE_CEILING = 100

# --- loyalty ---
LOYALTY_DISCOUNT = {"STANDARD": Decimal("0.00"), "PREFERRED": Decimal("0.10"), "TRADE": Decimal("0.15")}


def D(value):
    return Decimal(str(value))


def round2(value):
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def to_float(dec):
    return float(dec)


def line_cost(line, variant):
    """Per-line cost. variant is 'NOMINAL' or 'MEASURED'.

    Returns a Decimal rounded to 2 dp.
    """
    if variant == "NOMINAL":
        w = D(line["nominal_width_in"])
        h = D(line["nominal_height_in"])
    else:
        w = D(line["measured_width_in"])
        h = D(line["measured_height_in"])

    mat_border = D(line["mat_border_in"])
    mat_layers = D(line["mat_layers"])
    glass_type = line["glass_type"]
    molding_rate = D(line["molding_rate_per_ui"])
    mounting_type = line["mounting_type"]
    conservation = bool(line["conservation_package"])

    outer_w = w + 2 * mat_border
    outer_h = h + 2 * mat_border
    ui = outer_w + outer_h
    area_sqft = (outer_w * outer_h) / Decimal("144")

    molding_cost = round2(ui * molding_rate)
    mat_cost = round2(area_sqft * MAT_RATE_PER_SQFT * mat_layers)
    glass_cost = round2(area_sqft * GLASS_RATE[glass_type])

    if ui >= UI_TIER2:
        oversize = OVERSIZE_TIER2
    elif ui >= UI_TIER1:
        oversize = OVERSIZE_TIER1
    else:
        oversize = Decimal("0.00")

    mount_cost = MOUNT_UPCHARGE[mounting_type]

    materials = mat_cost + glass_cost
    if conservation:
        materials = round2(materials * CONSERVATION_MULT)

    line_subtotal = round2(molding_cost + materials + oversize + mount_cost + LABOR_PER_LINE)
    return line_subtotal


def quote_estimate_total(non_void_lines_sorted, rush_requested, loyalty_discount_pct):
    """SUM-THEN-ROUND. lines already ordered by created_at ASC, using estimate_subtotal."""
    raw = sum((D(l["estimate_subtotal"]) for l in non_void_lines_sorted), Decimal("0"))
    rushed = raw * (Decimal("1") + RUSH_PCT) if rush_requested else raw
    disc = D(loyalty_discount_pct)
    estimate = round2(rushed * (Decimal("1") - disc))
    return estimate


def final_invoice_total(measured_lines_sorted, rush_requested, loyalty_discount_pct):
    """ROUND-PER-LINE-THEN-SUM. lines (line_status==MEASURED) ordered by created_at ASC."""
    disc = D(loyalty_discount_pct)
    discounted_sum = Decimal("0")
    for l in measured_lines_sorted:
        discounted_sum += round2(D(l["final_subtotal"]) * (Decimal("1") - disc))
    if rush_requested:
        return round2(discounted_sum * (Decimal("1") + RUSH_PCT))
    return round2(discounted_sum)


def deposit_required(estimate_total, deposit_pct, has_fragile_line):
    pct = D(deposit_pct)
    if has_fragile_line and pct < FRAGILE_DEPOSIT_FLOOR_PCT:
        pct = FRAGILE_DEPOSIT_FLOOR_PCT
    raw = round2(D(estimate_total) * pct)
    return max(MIN_DEPOSIT, raw)


def turnaround_days(rush_requested, has_fragile_line):
    base = BASE_TURNAROUND_DAYS
    if rush_requested:
        base = math.ceil(base / 2)
    if has_fragile_line:
        base = base + FRAGILE_EXTRA_DAYS
    return base


def forward_no_show_risk(open_orders):
    """open_orders: list of order dicts whose production_status NOT IN {PICKED_UP, CANCELLED}."""
    ready_unpaid = [
        o
        for o in open_orders
        if o["production_status"] == "READY" and o["payment_status"] != "PAID_IN_FULL"
    ]
    score = len(open_orders) * OPEN_WEIGHT + len(ready_unpaid) * READY_UNPAID_WEIGHT
    return min(RISK_CEILING, score)


def settled_reputation(outcomes_chronological):
    """outcomes_chronological: list of 'ONTIME'/'ABANDON' in terminal-transition created_at order."""
    score = SEED_BASE
    for outcome in outcomes_chronological:
        if outcome == "ONTIME":
            score = score - ONTIME_DELTA
        elif outcome == "ABANDON":
            score = score + ABANDON_DELTA
        # clamp AFTER EACH step (order-sensitive)
        score = max(SCORE_FLOOR, min(SCORE_CEILING, score))
    return score


def order_ledger(applied_payments, estimate_total, final_invoice_total_val):
    """Returns (amount_paid, balance_due) as Decimals rounded to 2 dp."""
    paid = Decimal("0")
    for p in applied_payments:
        if p["kind"] in ("DEPOSIT", "BALANCE"):
            paid += D(p["amount"])
        elif p["kind"] == "REFUND":
            paid -= D(p["amount"])
    amount_paid = round2(paid)
    fin = D(final_invoice_total_val)
    if fin > 0:
        effective_total = fin
    else:
        effective_total = D(estimate_total)
    balance_due = round2(effective_total - amount_paid)
    return amount_paid, balance_due
