"""Calculation rules (PRD §2.6, §3.2-§3.9, SCAFFOLD §1.3).

All money is integer cents. Each per-unit cost term is rounded to the nearest
whole cent with round-half-up BEFORE terms are summed (round-per-term).
"""
import math
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING

# Constants (SCAFFOLD §1.3)
LABOR_RATE_CENTS_PER_HOUR = 6500
RUSH_TIER1_CENTS = 50000
RUSH_PCT_LOW = Decimal("0.15")
RUSH_PCT_HIGH = Decimal("0.30")
STANDARD_BASE_DAYS = 3
HOURS_PER_DAY = 8
RUSH_COMPRESS = Decimal("0.5")
RUSH_FLOOR_DAYS = 2
WARRANTY_DAYS = 90
DEPOSIT_PCT = Decimal("0.30")


def _round_half_up(value):
    """Round a Decimal to the nearest whole integer, half-up."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _d(x):
    """Convert a number (possibly float) to Decimal exactly via its repr."""
    return Decimal(str(x))


def round_cents(quantity, unit_price_cents):
    """round(quantity * unit_price) to whole cents, half-up."""
    return _round_half_up(_d(quantity) * _d(unit_price_cents))


# --------------------------------------------------------------------------
# per_piece_subtotal (PRD §3.2)
# --------------------------------------------------------------------------
def piece_subtotal(service_type, labor_hours, yardage_required, board_feet_required,
                   fabric_price_per_yard, foam_spec_id, foam_price_per_board_foot):
    labor_cost = round_cents(labor_hours, LABOR_RATE_CENTS_PER_HOUR)
    fabric_cost = round_cents(yardage_required, fabric_price_per_yard) \
        if service_type == "REUPHOLSTERY" else 0
    foam_cost = round_cents(board_feet_required, foam_price_per_board_foot) \
        if foam_spec_id is not None else 0
    return labor_cost + fabric_cost + foam_cost


# --------------------------------------------------------------------------
# estimate_total (PRD §3.3) — forward-looking, catalog prices.
# Returns (labor_total, materials_total, rush_surcharge, total).
# --------------------------------------------------------------------------
def estimate_totals(line_items, service_type, rush_requested,
                    fabric_price_lookup, foam_price_lookup):
    labor_total = 0
    materials_total = 0
    for li in line_items:
        labor_total += round_cents(li["labor_hours"], LABOR_RATE_CENTS_PER_HOUR)
        if service_type == "REUPHOLSTERY":
            fabric_price = fabric_price_lookup(li["fabric_sku_id"])
            materials_total += round_cents(li["yardage_required"], fabric_price)
        if li.get("foam_spec_id") is not None:
            foam_price = foam_price_lookup(li["foam_spec_id"])
            materials_total += round_cents(li["board_feet_required"], foam_price)
    base = labor_total + materials_total
    rush_surcharge = rush_surcharge_cents(labor_total, rush_requested)
    total = base + rush_surcharge
    return labor_total, materials_total, rush_surcharge, total


def rush_surcharge_cents(labor_total_cents, rush_requested):
    if not rush_requested:
        return 0
    if labor_total_cents <= RUSH_TIER1_CENTS:
        return _round_half_up(_d(labor_total_cents) * RUSH_PCT_LOW)
    low_term = _round_half_up(_d(RUSH_TIER1_CENTS) * RUSH_PCT_LOW)
    high_term = _round_half_up(_d(labor_total_cents - RUSH_TIER1_CENTS) * RUSH_PCT_HIGH)
    return low_term + high_term


# --------------------------------------------------------------------------
# material provisional/finalized cost (PRD §3.5)
# --------------------------------------------------------------------------
def provisional_cost(yards_ordered, fabric_price_per_yard,
                     board_feet_ordered, foam_price_per_board_foot):
    fabric_part = round_cents(yards_ordered, fabric_price_per_yard)
    foam_part = round_cents(board_feet_ordered, foam_price_per_board_foot)
    return fabric_part + foam_part


def finalized_cost(yards_ordered, received_fabric_price,
                   board_feet_ordered, received_foam_price):
    fabric_part = round_cents(yards_ordered, received_fabric_price)
    foam_part = round_cents(board_feet_ordered, received_foam_price)
    return fabric_part + foam_part


# --------------------------------------------------------------------------
# final_invoice (PRD §3.7) — chronological actuals.
# received_material_orders must be sorted created_at ASC by caller.
# --------------------------------------------------------------------------
def final_invoice(line_items, received_material_orders, approved_rush_surcharge):
    labor_total = sum(
        round_cents(li["labor_hours"], LABOR_RATE_CENTS_PER_HOUR)
        for li in line_items
    )
    materials_actual = sum(mo["finalized_cost_cents"] for mo in received_material_orders)
    return labor_total + materials_actual + approved_rush_surcharge


# --------------------------------------------------------------------------
# turnaround (PRD §3.4)
# --------------------------------------------------------------------------
def turnaround_days(line_items, rush_requested):
    total_labor_hours = sum(_d(li["labor_hours"]) for li in line_items)
    if not line_items:
        total_labor_hours = Decimal("0")
    base_band = STANDARD_BASE_DAYS + int(
        (total_labor_hours / HOURS_PER_DAY).to_integral_value(rounding=ROUND_CEILING)
    )
    if rush_requested:
        compressed = int(
            (_d(base_band) * RUSH_COMPRESS).to_integral_value(rounding=ROUND_CEILING)
        )
        return max(RUSH_FLOOR_DAYS, compressed)
    return base_band


# --------------------------------------------------------------------------
# warranty coverage (PRD §3.9)
# --------------------------------------------------------------------------
def warranty_covered(order_completed, completed_at_epoch, filed_at_epoch):
    if not order_completed:
        return False
    days_elapsed = math.floor((filed_at_epoch - completed_at_epoch) / 86400)
    return days_elapsed <= WARRANTY_DAYS


# --------------------------------------------------------------------------
# balance_due (PRD §3.7)
# --------------------------------------------------------------------------
def balance_due(final_invoice_cents, estimate_total_cents, amount_paid_cents):
    basis = final_invoice_cents if final_invoice_cents > 0 else estimate_total_cents
    return basis - amount_paid_cents


def required_deposit(estimate_total_cents):
    return int((_d(estimate_total_cents) * DEPOSIT_PCT).to_integral_value(
        rounding=ROUND_CEILING))
