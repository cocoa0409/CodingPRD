"""Calculation rules (SCAFFOLD §1.3 / PRD §2.5, §3.4-3.9)."""
import math
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR

# order_net_total constants
VOLUME_THRESHOLD_CENTS = 500000
VOLUME_BONUS_RATE = Decimal("0.05")
MAX_DISCOUNT_RATE = Decimal("0.12")
HAZMAT_BASE_CENTS = 1500
HAZMAT_PER_KG_CENTS = 200
HAZMAT_CAP_CENTS = 5000

BASE_DISCOUNT = {
    "STANDARD": Decimal("0.00"),
    "SILVER": Decimal("0.05"),
    "GOLD": Decimal("0.10"),
}

# loyalty
POINTS_DIVISOR_CENTS = 100
LOYALTY_MULT = {
    "BRONZE": Decimal("1.0"),
    "SILVER": Decimal("1.25"),
    "GOLD": Decimal("1.5"),
}

# rma
RESTOCK_FEE_RATE = Decimal("0.15")
WARRANTY_DAYS_PER_MONTH = 30


def round_half_up(value):
    """Round a Decimal to whole cents, ties away from zero -> int."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def order_net_total(lines, order_type, discount_tier):
    """Compute pricing over an order's lines.

    lines: list of dicts {unit_price_cents, quantity, _is_hazmat, _unit_weight_g}
    Returns (subtotal, discount_cents, hazmat_surcharge_cents, net_total).
    """
    subtotal = sum(l["unit_price_cents"] * l["quantity"] for l in lines)

    if order_type == "RETAIL":
        discount_rate = Decimal("0.00")
    else:
        base_rate = BASE_DISCOUNT[discount_tier]
        volume_bonus = VOLUME_BONUS_RATE if subtotal >= VOLUME_THRESHOLD_CENTS else Decimal("0.00")
        discount_rate = min(base_rate + volume_bonus, MAX_DISCOUNT_RATE)
    discount_cents = round_half_up(Decimal(subtotal) * discount_rate)

    if any(l.get("_is_hazmat") for l in lines):
        total_weight_g = sum(l.get("_unit_weight_g", 0) * l["quantity"] for l in lines)
        kg = math.ceil(total_weight_g / 1000)
        hazmat = HAZMAT_BASE_CENTS + HAZMAT_PER_KG_CENTS * kg
        hazmat_surcharge = min(hazmat, HAZMAT_CAP_CENTS)
    else:
        hazmat_surcharge = 0

    net_total = subtotal - discount_cents + hazmat_surcharge
    return subtotal, discount_cents, hazmat_surcharge, net_total


def loyalty_points_earned(line_totals, loyalty_tier):
    """Per-line floor, then sum (PRD §3.5)."""
    mult = LOYALTY_MULT[loyalty_tier]
    earned = 0
    for lt in line_totals:
        pts = (Decimal(lt) / Decimal(POINTS_DIVISOR_CENTS) * mult).to_integral_value(rounding=ROUND_FLOOR)
        earned += int(pts)
    return earned


def loyalty_tier_for(points):
    if points >= 5000:
        return "GOLD"
    if points >= 1000:
        return "SILVER"
    return "BRONZE"


def estimated_fee(hourly_rate_cents, scheduled_minutes):
    hours = math.ceil(scheduled_minutes / 60)
    return hourly_rate_cents * hours


def actual_fee(hourly_rate_cents, actual_minutes):
    return round_half_up(Decimal(hourly_rate_cents) * Decimal(actual_minutes) / Decimal(60))


def rma_refund(unit_price_cents, return_quantity, within_warranty):
    base_cents = unit_price_cents * return_quantity
    if within_warranty:
        return base_cents
    return round_half_up(Decimal(base_cents) * (Decimal("1") - RESTOCK_FEE_RATE))
