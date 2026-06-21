"""Calculation rules (SCAFFOLD §1.3, PRD §3.5–§3.9).

All money is integer cents. Fractional results are rounded half up using
Decimal — never float.
"""
from decimal import Decimal, ROUND_HALF_UP

# work_order_cost constants
TRIP_FEE_CENTS = 9000
BASE_INCLUDED_GALLONS = 1000
TIER1_RATE_CENTS = 25
TIER2_RATE_CENTS = 40
EMERGENCY_SURCHARGE_BPS = 5000

# site_risk_score constants
RESULT_WEIGHT = {"PASS": 0, "CONDITIONAL": 30, "FAIL": 60}
DEFECT_WEIGHT = 8
DEFECT_CAP = 24
OLD_ASSET_YEARS = 25
AGE_PENALTY = 15
REJECTION_PENALTY = 20

# temporal gate constants
COOLING_OFF_HOURS = 48
SITE_BUFFER_MINUTES = 120


def round_half_up(value):
    """Round a numeric value to the nearest integer, halves rounding up."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def work_order_cost(gallons, emergency_surcharge_applies):
    """Tiered pump cost on a flat trip fee, plus optional emergency surcharge.

    Used for both estimate and final variants; the caller picks which gallons
    to feed and which field to write.
    """
    gallons = gallons or 0
    if gallons < 0:
        gallons = 0
    tier1_gallons = min(gallons, BASE_INCLUDED_GALLONS)
    overage_gallons = max(gallons - BASE_INCLUDED_GALLONS, 0)
    pump_cents = tier1_gallons * TIER1_RATE_CENTS + overage_gallons * TIER2_RATE_CENTS
    cents = TRIP_FEE_CENTS + pump_cents
    if emergency_surcharge_applies:
        surcharge = round_half_up(
            Decimal(cents) * Decimal(EMERGENCY_SURCHARGE_BPS) / Decimal(10000)
        )
        cents = cents + surcharge
    return cents


def repair_line_total(quantity, unit_price_cents, tax_rate_bps):
    """Per-line total: quantity * unit_price * (1 + bps/10000), rounded half up."""
    raw = (
        Decimal(quantity)
        * Decimal(unit_price_cents)
        * (Decimal(1) + Decimal(tax_rate_bps) / Decimal(10000))
    )
    return round_half_up(raw)


def invoice_total(final_cost_cents, repair_lines):
    """final_cost + sum of per-line (already-rounded) totals.

    Order pinned: round each line first, THEN sum (never sum-then-round). Lines
    are processed in created_at ascending order.
    """
    parts_total = 0
    for rl in repair_lines:
        parts_total += rl["line_total_cents"]
    return final_cost_cents + parts_total


def site_risk_base(result, defect_count, newest_active_install_year, current_year):
    """Shared base+defect+age computation, clamped to 0..100."""
    base = RESULT_WEIGHT.get(result, 0)
    defect_component = min((defect_count or 0) * DEFECT_WEIGHT, DEFECT_CAP)
    age_component = 0
    if newest_active_install_year is not None:
        if (current_year - newest_active_install_year) >= OLD_ASSET_YEARS:
            age_component = AGE_PENALTY
    raw = base + defect_component + age_component
    return max(0, min(100, raw))


def site_risk_provisional(result, defect_count, newest_active_install_year, current_year):
    return site_risk_base(result, defect_count, newest_active_install_year, current_year)


def site_risk_final_approve(result, defect_count, newest_active_install_year, current_year):
    """APPROVE: relief = result base; score becomes max(0, score - base)."""
    score = site_risk_base(result, defect_count, newest_active_install_year, current_year)
    relief = RESULT_WEIGHT.get(result, 0)
    return max(0, score - relief)


def site_risk_final_reject(result, defect_count, newest_active_install_year, current_year):
    """REJECT: add rejection penalty, then clamp to 0..100."""
    score = site_risk_base(result, defect_count, newest_active_install_year, current_year)
    return max(0, min(100, score + REJECTION_PENALTY))
