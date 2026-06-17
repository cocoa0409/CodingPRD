"""Calculation engines (SCAFFOLD §1.3, PRD §3, §2.10).

All money is integer cents. round_half_up is applied at pinned steps.
"""
from helpers import round_half_up, round_half_up_2, to_date

# Per-minute machine rates in cents (PRD §2.10)
RATE = {
    "MILL_3AX": 180,
    "MILL_5AX": 320,
    "LATHE": 150,
}

# Margin tier bounds (exclusive upper) and percentages
MARGIN_TIER_LOW_MAX = 50000
MARGIN_TIER_MID_MAX = 200000
MARGIN_PCT_LOW = 35
MARGIN_PCT_MID = 25
MARGIN_PCT_HIGH = 18

# Penalty constants
UNIT_PENALTY_PER_DAY_CENTS = 50
PENALTY_CAP_CENTS = 20000

# Tax
TAX_PCT = 8.25


def margin_for(extended_cost_cents):
    if extended_cost_cents < MARGIN_TIER_LOW_MAX:
        return MARGIN_PCT_LOW
    if extended_cost_cents < MARGIN_TIER_MID_MAX:
        return MARGIN_PCT_MID
    return MARGIN_PCT_HIGH


def quote_estimate_cost(quote, routing_ops, quantity):
    """ESTIMATE variant (PRD §3.2).

    Returns dict with extended_cost_cents, margin_pct,
    quoted_price_cents, quoted_unit_price_cents.
    """
    q = quantity
    scrap = quote.get("scrap_allowance_pct") or 0

    labor_total = 0
    for op in routing_ops:
        rate = RATE[op["machine_class"]]
        # round per-part labor, THEN multiply by qty, THEN add setup
        per_part = round_half_up(op["estimated_cycle_min"] * rate)
        op_labor = per_part * q + (op.get("setup_fee_cents") or 0)
        labor_total += op_labor

    # material: round the marked-up per-part cost, THEN multiply
    mat_per_part = round_half_up(quote["material_unit_cost_cents"] * (1 + scrap / 100))
    material_total = mat_per_part * q

    extended = labor_total + material_total
    margin = margin_for(extended)
    quoted_price = round_half_up(extended * (1 + margin / 100))
    quoted_unit = round_half_up(quoted_price / q)

    return {
        "extended_cost_cents": extended,
        "margin_pct": margin,
        "quoted_price_cents": quoted_price,
        "quoted_unit_price_cents": quoted_unit,
    }


def work_order_actual_cost(wo, completed_ops, active_allocations, lots_by_id):
    """ACTUAL variant (PRD §3.4). No margin, no scrap markup."""
    q_started = wo["qty_started"]

    labor_actual = 0
    for op in completed_ops:
        rate = RATE[op["machine_class"]]
        per_part = round_half_up(op["actual_cycle_min"] * rate)
        op_actual = per_part * q_started + (op.get("setup_fee_cents") or 0)
        labor_actual += op_actual

    material_actual = 0
    for alloc in active_allocations:
        lot = lots_by_id[alloc["material_lot_id"]]
        material_actual += alloc["qty_allocated"] * lot["unit_cost_cents"]

    return labor_actual + material_actual


def shipment_on_time_and_penalty(qty_shipped, promised_dt, actual_dt):
    """Date-precision on-time + liquidated damages (PRD §3.6)."""
    p_date = to_date(promised_dt)
    a_date = to_date(actual_dt)

    on_time = a_date <= p_date
    days_late = max(0, (a_date - p_date).days)
    penalty = min(PENALTY_CAP_CENTS, qty_shipped * UNIT_PENALTY_PER_DAY_CENTS * days_late)

    return {
        "on_time": on_time,
        "days_late": days_late,
        "late_penalty_cents": penalty,
    }


def invoice_total(quoted_unit_price_cents, qty_shipped, late_penalty_cents):
    """Invoice subtotal/tax/penalty/total (PRD §3.7)."""
    subtotal = quoted_unit_price_cents * qty_shipped
    tax = round_half_up(subtotal * TAX_PCT / 100)
    penalty_credit = late_penalty_cents
    total = subtotal + tax - penalty_credit
    return {
        "subtotal_cents": subtotal,
        "tax_cents": tax,
        "penalty_credit_cents": penalty_credit,
        "total_cents": total,
    }


def first_pass_yield(qty_accepted, qty_inspected):
    """First-pass yield % to 2 dp; 0 when qty_inspected == 0 (PRD §3.5)."""
    if qty_inspected == 0:
        return 0
    return round_half_up_2(qty_accepted / qty_inspected * 100)
