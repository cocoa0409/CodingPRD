"""Calculation rules (scaffold §1.3 / PRD §2.5, §3).

All monetary quantities are integer cents. Non-integer cent results are rounded
to whole cents using round-half-up (away from zero at exactly .5) — PRD §2.5.
mod_factor / current_emr are the only non-cent numerics: round-half-up to 2 dp,
rounding applied before clamping (PRD §2.5).
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

# ---- TTD weekly rate constants (scaffold ttd_weekly_rate) ----
TTD_RATE = Decimal("0.6667")
SAWW_CENTS = 120000
MAX_COMP_PCT = Decimal("1.00")
MIN_TTD_CENTS = 15000

# ---- indemnity payment constants (scaffold indemnity_payment_amount) ----
WAITING_DAYS = 7
RETRO_DAYS = 14
TPD_RATE = Decimal("0.6667")
PPD_WEEKS_PER_PCT = Decimal("3.0")

# ---- reserve constants (scaffold indemnity_reserve_forward) ----
MED_TIER = {
    "MINOR": 250000,
    "MODERATE": 1500000,
    "SEVERE": 7500000,
}

# ---- experience-mod constants (scaffold experience_mod) ----
PRIMARY_SPLIT_CENTS = 1700000
MOD_FLOOR = Decimal("0.75")
MOD_CEILING = Decimal("2.00")

# ---- statutory time windows (PRD §3.2, §3.11) ----
SOL_DAYS = 730            # statute of limitations for opening a claim (2 years)
REOPEN_LIMIT_DAYS = 1825  # reopening window (5 years)
BUFFER_DAYS = 7           # RTW light-duty buffer gap


def _round_half_up(value: Decimal) -> int:
    """Round a Decimal to the nearest whole integer, half away from zero."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def average_weekly_wage(gross_wages_cents: int, weeks_worked: int) -> int:
    """AWW = round_half_up(gross_wages_cents / weeks_worked)."""
    return _round_half_up(Decimal(gross_wages_cents) / Decimal(weeks_worked))


def ttd_weekly_rate(average_weekly_wage_cents: int) -> int:
    """Capped-then-floored TTD weekly compensation rate in cents."""
    raw_cents = _round_half_up(Decimal(average_weekly_wage_cents) * TTD_RATE)
    cap_cents = _round_half_up(Decimal(SAWW_CENTS) * MAX_COMP_PCT)
    capped_cents = min(raw_cents, cap_cents)
    return max(capped_cents, MIN_TTD_CENTS)


def indemnity_payment_ttd(weekly_rate_cents: int, disability_days: int) -> int:
    """TTD payout from the controlling weekly rate and disability span.

    daily = round_half_up(weekly / 7).
    <= 7 days       -> 0 compensable
    8..13 days       -> (days - 7) compensable
    >= 14 days       -> all `days` compensable (waiting period paid retroactively)
    amount = round_half_up(daily * compensable_days)
    """
    daily = _round_half_up(Decimal(weekly_rate_cents) / Decimal(7))
    if disability_days <= WAITING_DAYS:
        compensable = 0
    elif disability_days < RETRO_DAYS:
        compensable = disability_days - WAITING_DAYS
    else:
        compensable = disability_days
    return _round_half_up(Decimal(daily) * Decimal(compensable))


def indemnity_payment_tpd(aww_cents: int, light_duty_weekly_cents: int, weekly_rate_cents: int) -> int:
    """TPD payout: wage-loss replacement, capped at the TTD weekly rate."""
    loss_weekly = aww_cents - light_duty_weekly_cents
    if loss_weekly <= 0:
        return 0
    raw = _round_half_up(Decimal(loss_weekly) * TPD_RATE)
    return min(raw, weekly_rate_cents)


def indemnity_payment_ppd(finalized_pct, weekly_rate_cents: int) -> int:
    """PPD payout: weeks = finalized_pct * 3.0; amount = round_half_up(weeks * weekly)."""
    weeks = Decimal(str(finalized_pct)) * PPD_WEEKS_PER_PCT
    return _round_half_up(weeks * Decimal(weekly_rate_cents))


def indemnity_reserve_forward(weekly_rate_cents: int, projected_weeks: int) -> int:
    """Forward indemnity reserve = round_half_up(weekly * projected_weeks)."""
    return _round_half_up(Decimal(weekly_rate_cents) * Decimal(projected_weeks))


def medical_reserve_for_tier(severity_tier: str) -> int:
    return MED_TIER[severity_tier]


def total_incurred(indemnity_reserve_cents: int, medical_reserve_cents: int,
                   indemnity_paid_cents: int, medical_paid_cents: int) -> int:
    return (indemnity_reserve_cents + medical_reserve_cents
            + indemnity_paid_cents + medical_paid_cents)


def experience_mod(actual_total_incurred_by_claim, weighting_factor,
                   ballast_cents, expected_primary_cents, expected_excess_cents):
    """Compute the experience-modification factor (EMR).

    Ap = sum over claims of min(total_incurred, PRIMARY_SPLIT_CENTS)
    Ae = sum over claims of max(total_incurred - PRIMARY_SPLIT_CENTS, 0)
    numerator   = Ap + W*Ae + (1-W)*Ee + B
    denominator = Ep + W*Ee + (1-W)*Ee + B   (== Ep + Ee + B)
    mod = clamp(round_half_up(numerator/denominator, 2 dp), 0.75, 2.00)
    """
    Ap = 0
    Ae = 0
    for ti in actual_total_incurred_by_claim:
        Ap += min(ti, PRIMARY_SPLIT_CENTS)
        Ae += max(ti - PRIMARY_SPLIT_CENTS, 0)

    W = Decimal(str(weighting_factor))
    B = Decimal(ballast_cents)
    Ep = Decimal(expected_primary_cents)
    Ee = Decimal(expected_excess_cents)
    one_minus_w = Decimal(1) - W

    numerator = Decimal(Ap) + (W * Decimal(Ae)) + (one_minus_w * Ee) + B
    denominator = Ep + (W * Ee) + (one_minus_w * Ee) + B

    raw_mod = numerator / denominator
    rounded = raw_mod.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    clamped = max(MOD_FLOOR, min(MOD_CEILING, rounded))
    return clamped


def modified_premium(manual_premium_cents: int, current_emr) -> int:
    """modified_premium_cents = round_half_up(manual_premium * current_emr)."""
    return _round_half_up(Decimal(manual_premium_cents) * Decimal(str(current_emr)))


def emr_as_float(mod_factor_decimal: Decimal) -> float:
    """Render a 2-dp mod factor as a JSON number (float)."""
    return float(mod_factor_decimal)
