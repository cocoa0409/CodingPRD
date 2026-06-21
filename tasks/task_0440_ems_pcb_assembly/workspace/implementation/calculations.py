"""Calculation rules (SCAFFOLD §1.3, PRD §2.5 / §3).

All monetary amounts are integer cents. Rate/factor products that must land on
whole cents are rounded half-up. first_pass_yield_pct carries two decimal
places, rounded half-up.
"""

from decimal import Decimal, ROUND_HALF_UP

# Constants
MIN_YIELD_PCT = 70
HANDLING_FLAT_CENTS = 1500
MID_RATE = Decimal("0.20")
HIGH_RATE = Decimal("0.30")
LOW_TIER_MAX = 5000
MID_TIER_MAX = 20000

WORKMANSHIP_FACTOR = Decimal("1.00")
COMPONENT_FACTOR = Decimal("0.60")
DESIGN_FACTOR = Decimal("0.80")
NO_FAULT_FACTOR = Decimal("0.00")
REWORK_PENALTY = Decimal("0.10")

_FACTORS = {
    "WORKMANSHIP": WORKMANSHIP_FACTOR,
    "COMPONENT": COMPONENT_FACTOR,
    "DESIGN": DESIGN_FACTOR,
    "NO_FAULT_FOUND": NO_FAULT_FACTOR,
}


def round_half_up_cents(value):
    """Round a Decimal to whole cents, half-up, return int."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_2dp(value):
    """Round a Decimal to 2 decimal places, half-up, return float."""
    q = Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(q)


def first_pass_yield_pct(total_tested, first_pass):
    """(first_pass / total_tested) * 100, 2dp half-up; 0 when no tests."""
    if total_tested <= 0:
        return 0.0
    val = (Decimal(first_pass) / Decimal(total_tested)) * Decimal(100)
    return round_half_up_2dp(val)


def handling_surcharge(base_part_cost):
    """Tiered surcharge on base_part_cost (integer cents). Upper-bound inclusive."""
    base = base_part_cost
    if base <= LOW_TIER_MAX:
        return HANDLING_FLAT_CENTS
    if base <= MID_TIER_MAX:
        return round_half_up_cents(Decimal(base) * MID_RATE)
    return round_half_up_cents(Decimal(base) * HIGH_RATE)


def rework_material_cost(base_part_cost):
    """added_material_cost_cents = base_part_cost + tiered handling surcharge."""
    return base_part_cost + handling_surcharge(base_part_cost)


def rma_warranty_credit(material_cost_cents, built_qty, failure_class, rework_count):
    """Warranty credit per PRD §3.10.

    unit_build_cost = material_cost_cents // built_qty (integer floor)
    base = round_half_up(unit_build_cost * factor)
    penalty = round_half_up(unit_build_cost * 0.10) when rework_count > 0 else 0
    final = max(0, base - penalty)
    """
    if built_qty <= 0:
        unit_build_cost = 0
    else:
        unit_build_cost = material_cost_cents // built_qty  # integer floor division
    factor = _FACTORS[failure_class]
    base = round_half_up_cents(Decimal(unit_build_cost) * factor)
    penalty = 0
    if rework_count > 0:
        penalty = round_half_up_cents(Decimal(unit_build_cost) * REWORK_PENALTY)
    final = base - penalty
    if final < 0:
        final = 0
    return final
