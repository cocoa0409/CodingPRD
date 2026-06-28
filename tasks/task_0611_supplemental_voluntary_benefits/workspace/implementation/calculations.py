"""Calculation rules (scaffold §1.3 / PRD §2.6, §3.5, §3.8, §3.10).

All monetary amounts are integer cents. Two rounding disciplines (PRD §2.6):
  - Premium scaling by basis points: round HALF UP to whole cents.
  - Per-pay-period deduction: FLOOR to whole cents (remainder carried to the
    year's final pay period at payroll time).
Basis points are interpreted against a denominator of 10000.
"""

from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR

BPS_DENOMINATOR = 10000
WEEKS_PER_YEAR = 52
LAPSE_THRESHOLD = 3


def _round_half_up(value):
    """Round a Decimal to a whole integer using round-half-up."""
    return int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def scale_by_bps(base_cents, bps):
    """base_cents * (1 + bps/10000), rounded half-up to whole cents (PRD §2.6)."""
    base = Decimal(base_cents)
    multiplier = Decimal(1) + (Decimal(bps) / Decimal(BPS_DENOMINATOR))
    return _round_half_up(base * multiplier)


def premium_assessment(product, period, enrolled_at):
    """Freeze gi_status + weekly_premium_cents at enrollment creation (PRD §3.5).

    GI-window membership boundary is [gi_window_start, gi_window_end):
      at-or-after start AND strictly-before end => GUARANTEED_ISSUE (base, no surcharge)
      otherwise                                  => EVIDENCE_REQUIRED (base scaled by EOI bps)
    """
    base = product["weekly_premium_cents"]
    gi_start = period["_gi_window_start_dt"]
    gi_end = period["_gi_window_end_dt"]

    if gi_start <= enrolled_at < gi_end:
        gi_status = "GUARANTEED_ISSUE"
        weekly_premium_cents = base
    else:
        gi_status = "EVIDENCE_REQUIRED"
        weekly_premium_cents = scale_by_bps(base, product["eoi_surcharge_bps"])

    return gi_status, weekly_premium_cents


def deduction_conversion(weekly_premium_cents, pay_periods_per_year):
    """Convert frozen weekly premium to per-pay-period deduction (PRD §3.5, §2.6).

    annual = weekly_premium_cents * 52
    weekly_deduction_cents = floor(annual / pay_periods_per_year)
    """
    annual = Decimal(weekly_premium_cents) * Decimal(WEEKS_PER_YEAR)
    quotient = annual / Decimal(pay_periods_per_year)
    floored = quotient.quantize(Decimal(1), rounding=ROUND_FLOOR)
    return int(floored)


def benefit_remaining(annual_cap_cents, benefit_paid_cents):
    """= annual_benefit_cap_cents - benefit_paid_cents, floored at 0 (PRD §3.5)."""
    return max(0, annual_cap_cents - benefit_paid_cents)


def claim_provisional(schedule_item):
    """Provisional claimed_cents at filing = raw flat benefit (PRD §3.8)."""
    return schedule_item["flat_benefit_cents"]


def claim_adjudicated(schedule_item, claimed_cents, annual_cap_cents, benefit_paid_cents):
    """Adjudicated approved_cents at approval (PRD §3.8).

    Wellness line: uncapped — approved_cents == claimed_cents (no ledger touch).
    Non-wellness:  remaining = max(0, cap - benefit_paid); approved = min(claimed, remaining).
    """
    if schedule_item["is_wellness"]:
        return claimed_cents
    remaining = max(0, annual_cap_cents - benefit_paid_cents)
    return min(claimed_cents, remaining)


def portability_premium(product):
    """Ported weekly premium from PRODUCT base (not enrollment surcharge) (PRD §3.10).

    direct_bill_weekly_cents = round_half_up(base * (1 + portability_loadup_bps/10000))
    """
    return scale_by_bps(product["weekly_premium_cents"], product["portability_loadup_bps"])
