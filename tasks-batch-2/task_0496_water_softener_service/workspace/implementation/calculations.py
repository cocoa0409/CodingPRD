"""Calculation rules from SCAFFOLD §1.3 / PRD §3. Money uses Decimal with
ROUND_HALF_UP; never float arithmetic for monetary results.
"""
import math
from decimal import Decimal, ROUND_HALF_UP

import constants as C


def _round_half_up(value):
    """Round a numeric value to the nearest whole integer, half up."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def size_grain_capacity(hardness_gpg, iron_ppm, household_size):
    """SCAFFOLD size_grain_capacity (PRD §3.2)."""
    effective_hardness = hardness_gpg + (iron_ppm * C.IRON_HARDNESS_EQUIV)
    daily_grains = household_size * C.GALLONS_PER_PERSON_DAY * effective_hardness
    required_capacity = math.ceil(daily_grains * C.REGEN_TARGET_DAYS)
    for tank in C.STANDARD_TANKS:
        if tank >= required_capacity:
            return tank
    return max(C.STANDARD_TANKS)


def needs_ro(tds_ppm):
    return tds_ppm >= C.RO_TDS_THRESHOLD


def capacity_gallons(grain_capacity, account_hardness_gpg):
    """regen_demand cycle capacity (PRD §3.3). Floor division by account
    hardness basis. Returns None when hardness is unusable (<= 0)."""
    if account_hardness_gpg is None or account_hardness_gpg <= 0:
        return None
    return int(math.floor(grain_capacity / account_hardness_gpg))


def regen_health_for(gallons_since_regen, cap_gallons):
    """Threshold crossing; >= boundary counts as crossed (PRD §3.3)."""
    if cap_gallons is None:
        return "NOMINAL"
    if gallons_since_regen >= cap_gallons * C.REGEN_GRACE_FACTOR:
        return "OVERDUE"
    if gallons_since_regen >= cap_gallons:
        return "DUE"
    return "NOMINAL"


def daily_rate_cents(monthly_rate_cents):
    """Daily rate rounded to whole cents BEFORE multiplying by day count."""
    return _round_half_up(Decimal(monthly_rate_cents) / Decimal(C.DAYS_PER_BILLING_MONTH))


def rental_amount(invoice_kind, monthly_rate_cents, billable_days):
    """rental_proration (PRD §3.10)."""
    if invoice_kind == "RENTAL_CYCLE":
        return monthly_rate_cents
    # PRORATION
    return daily_rate_cents(monthly_rate_cents) * billable_days


def early_termination_fee(start_date, now, term_months, monthly_rate_cents):
    """early_termination_fee (PRD §3.8)."""
    days_elapsed = (now - start_date).total_seconds() / 86400.0
    months_elapsed = int(math.floor(days_elapsed / C.DAYS_PER_BILLING_MONTH))
    months_remaining = max(0, term_months - months_elapsed)
    if months_remaining == 0:
        return 0
    if months_remaining <= C.TIER1_MONTHS:
        rate = C.TIER1_RATE
    elif months_remaining <= C.TIER2_MONTHS:
        rate = C.TIER2_RATE
    else:
        rate = C.TIER3_RATE
    raw = Decimal(months_remaining) * Decimal(monthly_rate_cents) * Decimal(str(rate))
    fee = _round_half_up(raw)
    return min(fee, C.FEE_CAP_CENTS)


def coverage_covered(defect_class, install_date, reported_at):
    """coverage_window (PRD §3.9). Boundary inclusive (<=)."""
    window_days = C.COVERAGE_DAYS[defect_class]
    age_days = int(math.floor((reported_at - install_date).total_seconds() / 86400.0))
    return age_days <= window_days


def claim_settlement(defect_class, covered, install_date, now):
    """claim_settlement (PRD §3.9)."""
    if covered:
        return 0
    base = C.DEFECT_BASE_COST[defect_class]
    age_days = (now - install_date).total_seconds() / 86400.0
    steps = int(math.floor(age_days / C.GOODWILL_STEP_DAYS))
    goodwill = min(C.GOODWILL_MAX, steps * C.GOODWILL_PCT_PER_STEP)
    labor = C.LABOR_FLAT_CENTS
    raw = Decimal(base + labor) * (Decimal(1) - Decimal(str(goodwill)))
    return _round_half_up(raw)
