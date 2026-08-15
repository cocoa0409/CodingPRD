"""Calculation rules: proration, subsidy tiers, payroll deduction cap,
utility overage pricing. All money math uses Decimal with ROUND_HALF_UP."""

import calendar
from decimal import Decimal, ROUND_HALF_UP

import clock
import db
from services import core


def _rh(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def prorated_rent_charge(unit, move_in_date):
    """Return integer cents for the move-in month's rent charge.
    Variant selected by unit.unit_type."""
    from datetime import date as _date
    monthly = unit["monthly_rent_cents"]
    days_in_month = calendar.monthrange(move_in_date.year, move_in_date.month)[1]
    last_day = _date(move_in_date.year, move_in_date.month, days_in_month)
    days_remaining = (last_day - move_in_date).days + 1  # inclusive of move_in_date

    if unit["unit_type"] == "FAMILY_UNIT":
        charge = _rh(Decimal(monthly) * Decimal(days_remaining) / Decimal(days_in_month))
        return charge
    else:  # SEASONAL_DORM -> weekly_slot
        weekly_rate = _rh(Decimal(monthly) * Decimal(12) / Decimal(52))
        weeks = -(-days_remaining // 7)  # ceil(days_remaining / 7)
        return weeks * weekly_rate


def subsidy_tier_and_credit(unit, household, prorated_charge_cents):
    """Return (tier_decimal, credit_cents). Tier keyed on GROSS rent.
    monthly_income == 0 -> max tier 0.30."""
    gross_monthly = unit["monthly_rent_cents"]
    annual = household["annual_family_income_cents"]
    monthly_income = _rh(Decimal(annual) / Decimal(12))

    if monthly_income == 0:
        tier = Decimal("0.30")
    else:
        ratio = Decimal(gross_monthly) / Decimal(monthly_income)
        if ratio >= Decimal("0.50"):
            tier = Decimal("0.30")
        elif ratio >= Decimal("0.30"):
            tier = Decimal("0.15")
        else:
            tier = Decimal("0")

    credit = _rh(tier * Decimal(prorated_charge_cents))
    return tier, credit


def payroll_deduction_cap(gross_wages_cents, cap_percent, covered_balance):
    """Smallest of four rounded candidates. Returns integer cents (may be <= 0)."""
    gross = Decimal(gross_wages_cents)
    c1 = _rh(Decimal(str(cap_percent)) * gross)
    c2 = _rh(core.FEDERAL_MAX_PCT * gross)
    c3 = _rh(gross - Decimal(core.MIN_NET_WAGE_FLOOR_CENTS))
    c4 = _rh(covered_balance)
    return min(c1, c2, c3, c4)


def utility_overage_charge(usage_lines):
    """Per-line pricing with per-line rounding, then integer sum.
    Returns integer cents."""
    total = 0
    for line in usage_lines:
        utility_type = line["utility_type"]
        usage_units = line["usage_units"]
        allowance = core.ALLOWANCE[utility_type]
        overage = max(0, usage_units - allowance)
        tier1 = min(overage, core.TIER1_SPAN)
        tier2 = overage - tier1
        raw = (Decimal(tier1) * core.TIER1_RATE_TENTH_CENTS / Decimal(10)
               + Decimal(tier2) * core.TIER2_RATE_TENTH_CENTS / Decimal(10))
        line_cents = _rh(raw)
        total += line_cents
    return total
