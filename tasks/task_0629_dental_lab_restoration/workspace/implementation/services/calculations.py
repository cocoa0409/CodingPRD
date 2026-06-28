"""Calculation rules (scaffold §1.3, PRD §3.3 / §3.6).

All money is integer cents. round_half_up at each named step in the pinned order;
never float. Decimal with ROUND_HALF_UP.
"""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

# Type complexity factors (scaffold line_item_pricing constants / PRD §3.3).
TYPE_COMPLEXITY = {
    "CROWN": Decimal("1.00"),
    "BRIDGE": Decimal("1.25"),
    "DENTURE": Decimal("2.00"),
    "ALIGNER": Decimal("0.30"),
}

# Per-type turnaround hours (scaffold turnaround_promise constants / PRD §3.3).
TURN_HOURS = {
    "CROWN": 120,
    "BRIDGE": 168,
    "DENTURE": 240,
    "ALIGNER": 336,
}
RUSH_FLOOR_HOURS = 24

# invoice_total constants (scaffold §1.3 / PRD §3.3, §3.6).
RUSH_PCT = Decimal("0.50")
TAX_PCT = Decimal("0.0825")
SLA_CREDIT_PCT = Decimal("0.20")

# Volume discount tiers (scaffold §1.3 / PRD §3.3).
TIER_0_MAX = 4        # 0..4 -> 0%
TIER_1_MIN = 5        # 5..19 -> 5%
TIER_1_PCT = Decimal("0.05")
TIER_2_MIN = 20       # 20+ -> 10%
TIER_2_PCT = Decimal("0.10")

# Revision cap (PRD §3.5 "maximum of three revisions").
MAX_REVISIONS = 3


def round_half_up(value):
    """Round a Decimal to a whole integer of cents, half away from zero."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def volume_tier_pct(completed_case_count):
    """Doctor volume-tier percentage from completed_case_count (PRD §3.3)."""
    if completed_case_count <= TIER_0_MAX:
        return Decimal("0")
    if completed_case_count < TIER_2_MIN:  # 5..19
        return TIER_1_PCT
    return TIER_2_PCT  # 20+


def unit_price_cents(base_unit_price_cents, restoration_type):
    """line_item_pricing: round per unit to whole cents BEFORE any summation (PRD §3.3).

    unit_price = round_half_up(base_unit_price_cents * type_factor)
    """
    factor = TYPE_COMPLEXITY[restoration_type]
    return round_half_up(Decimal(base_unit_price_cents) * factor)


def turnaround_promise(scheduled_start_at, restoration_types, is_rush):
    """turnaround_promise (PRD §3.3): promised_ready_at.

    base_hours = max over restorations of TURN_HOURS[type]
    promised_hours = base_hours if not rush else max(base_hours // 2, 24)
    promised_ready_at = scheduled_start_at + promised_hours hours
    """
    base_hours = max(TURN_HOURS[t] for t in restoration_types)
    if not is_rush:
        promised_hours = base_hours
    else:
        promised_hours = max(base_hours // 2, RUSH_FLOOR_HOURS)
    return scheduled_start_at + timedelta(hours=promised_hours)


def invoice_total(subtotal_cents, is_rush, completed_case_count, is_final, sla_breached):
    """invoice_total (PRD §3.3 provisional / §3.6 final).

    Pinned order: rush before discount, discount before tax, sla_credit last.
    Returns dict of the computed integer-cent amounts.
    """
    subtotal = Decimal(subtotal_cents)

    rush_surcharge = round_half_up(subtotal * RUSH_PCT) if is_rush else 0
    pre_discount = subtotal_cents + rush_surcharge

    tier_pct = volume_tier_pct(completed_case_count)
    discount = round_half_up(Decimal(pre_discount) * tier_pct)

    taxable = pre_discount - discount
    tax = round_half_up(Decimal(taxable) * TAX_PCT)

    if is_final and sla_breached:
        sla_credit = round_half_up(subtotal * SLA_CREDIT_PCT)
    else:
        sla_credit = 0

    total = taxable + tax - sla_credit

    return {
        "subtotal_cents": subtotal_cents,
        "rush_surcharge_cents": rush_surcharge,
        "discount_cents": discount,
        "tax_cents": tax,
        "sla_credit_cents": sla_credit,
        "total_cents": total,
    }
