"""Money and tier calculations — single-rounding integer-cent arithmetic.

All monetary fields are stored in integer cents. Intermediate values are kept
at full precision (via `decimal.Decimal`) and round-half-up is applied exactly
once at the end of each named calculation.
"""

from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timedelta, timezone

import clock


# ---------------------------------------------------------------------------
# Slot-fee calculation — calc_slot_fee
# ---------------------------------------------------------------------------

TIER_DISCOUNT_PCT = {"BRONZE": 0, "SILVER": 5, "GOLD": 10, "PLATINUM": 15}
PACKAGE_DISCOUNT_PCT = {"STANDARD": 0, "COMBO_HALF_DAY": 8,
                        "COMBO_FULL_DAY": 12, "PEAK_BUNDLE": 5}
PEAK_MULTIPLIER = Decimal("0.50")
DEPOSIT_FRACTION = Decimal("0.30")

PEAK_START_HOUR = 19  # 19:00 UTC inclusive
PEAK_END_HOUR = 23    # 23:00 UTC exclusive


def _round_half_up(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _minutes_in_peak_window(starts_at: datetime, ends_at: datetime) -> int:
    """Count minutes of the half-open interval [starts_at, ends_at) that fall
    inside the peak window 19:00–23:00 UTC on any date.

    Implementation: iterate minute-by-minute. Intervals are at most 8h, so up
    to 480 minutes — fast in Python.
    """
    if ends_at <= starts_at:
        return 0
    if starts_at.tzinfo is None:
        starts_at = starts_at.replace(tzinfo=timezone.utc)
    if ends_at.tzinfo is None:
        ends_at = ends_at.replace(tzinfo=timezone.utc)

    # Snap starts_at down to the nearest minute (its second/microsecond should
    # already be zero for sensible inputs; but guard anyway).
    minute_zero = starts_at.replace(second=0, microsecond=0)
    if minute_zero < starts_at:
        # If starts_at has sub-minute component, only the remaining part of
        # this minute counts — but the spec treats minute granularity, so we
        # use the minute that contains starts_at as the first peak-candidate.
        pass

    count = 0
    minute = starts_at
    one_min = timedelta(minutes=1)
    # Iterate at the minute granularity of the half-open interval.
    while minute < ends_at:
        hour = minute.astimezone(timezone.utc).hour
        if PEAK_START_HOUR <= hour < PEAK_END_HOUR:
            count += 1
        minute = minute + one_min
    return count


def calc_slot_fee(*, base_hour_price_cents: int,
                  starts_at: datetime, ends_at: datetime,
                  tier: str, package_code: str) -> dict:
    """Compute the slot fee for `tier` and `package_code`.

    Returns a dict with `total_cents`, `subtotal_cents`, `peak_surcharge_cents`,
    `package_discount_cents`. The single end-of-calculation rounding is applied
    to `total_cents` only; the breakdown fields are intermediate roundings used
    for reporting on the invoice (see PRD §3.5).
    """
    bhp = Decimal(int(base_hour_price_cents))
    duration_seconds = Decimal((ends_at - starts_at).total_seconds())
    duration_hours = duration_seconds / Decimal(3600)

    base_cents = bhp * duration_hours

    peak_minutes = _minutes_in_peak_window(starts_at, ends_at)
    peak_hours = Decimal(peak_minutes) / Decimal(60)
    peak_surcharge_cents = peak_hours * bhp * PEAK_MULTIPLIER

    subtotal_unrounded = base_cents + peak_surcharge_cents

    tier_pct = Decimal(TIER_DISCOUNT_PCT[tier]) / Decimal(100)
    package_pct = Decimal(PACKAGE_DISCOUNT_PCT[package_code]) / Decimal(100)

    step1 = subtotal_unrounded * (Decimal(1) - tier_pct)
    step2 = step1 * (Decimal(1) - package_pct)
    total_cents = _round_half_up(step2)

    # Breakdown fields for the invoice (PRD §3.5):
    # subtotal_cents = base + peak (sum), rounded for invoice display
    subtotal_cents = _round_half_up(subtotal_unrounded)
    peak_surcharge_int = _round_half_up(peak_surcharge_cents)
    # package_discount_cents = the absolute cent reduction the package discount
    # contributed relative to the tier-adjusted (rounded-at-end) subtotal.
    step1_rounded = _round_half_up(step1)
    package_discount_int = step1_rounded - total_cents

    return {
        "total_cents": total_cents,
        "subtotal_cents": subtotal_cents,
        "peak_surcharge_cents": peak_surcharge_int,
        "package_discount_cents": package_discount_int,
    }


def deposit_for_total(total_cents: int) -> int:
    """30% of total_cents, single round-half-up."""
    return _round_half_up(Decimal(int(total_cents)) * DEPOSIT_FRACTION)


# ---------------------------------------------------------------------------
# Commission calculation — calc_commission
# ---------------------------------------------------------------------------

RATE_BP = {"BRONZE": 1200, "SILVER": 1500, "GOLD": 1800, "PLATINUM": 2200}
TIER_BONUS_THRESHOLD_CENTS = 5_000_000
TIER_BONUS_PCT = Decimal("0.005")
TAX_RATE = Decimal("0.10")


def calc_commission_provisional(*, pinned_tier: str,
                                gross_sales_cents: int) -> dict:
    """Provisional commission at end-live. Uses gross sales only, no tax."""
    rate_bp = RATE_BP[pinned_tier]
    gross = Decimal(int(gross_sales_cents))
    gross_commission_cents = _round_half_up(gross * Decimal(rate_bp) / Decimal(10000))
    tier_bonus_cents = 0
    if pinned_tier in ("GOLD", "PLATINUM") and gross_sales_cents >= TIER_BONUS_THRESHOLD_CENTS:
        tier_bonus_cents = _round_half_up(gross * TIER_BONUS_PCT)
    provisional_payout_cents = gross_commission_cents + tier_bonus_cents
    return {
        "commission_rate_bp": rate_bp,
        "gross_commission_cents": gross_commission_cents,
        "tier_bonus_cents": tier_bonus_cents,
        "provisional_payout_cents": provisional_payout_cents,
    }


def calc_commission_final(*, pinned_tier: str,
                          gross_sales_cents: int,
                          returned_sales_cents: int,
                          previous_gross_commission_cents: int) -> dict:
    """Final commission at sweep. Applies returns, recomputes tier bonus on
    effective sales, and withholds tax.
    """
    rate_bp = RATE_BP[pinned_tier]
    effective_sales_cents = gross_sales_cents - returned_sales_cents
    reversed_commission_cents = _round_half_up(
        Decimal(int(returned_sales_cents)) * Decimal(rate_bp) / Decimal(10000))
    adjusted_gross_cents = previous_gross_commission_cents - reversed_commission_cents
    adjusted_bonus_cents = 0
    if pinned_tier in ("GOLD", "PLATINUM") and effective_sales_cents >= TIER_BONUS_THRESHOLD_CENTS:
        adjusted_bonus_cents = _round_half_up(
            Decimal(int(effective_sales_cents)) * TIER_BONUS_PCT)
    pre_tax = adjusted_gross_cents + adjusted_bonus_cents
    if pre_tax > 0:
        tax_withholding_cents = _round_half_up(Decimal(pre_tax) * TAX_RATE)
    else:
        tax_withholding_cents = 0
    final_payout_cents = pre_tax - tax_withholding_cents
    return {
        "commission_rate_bp": rate_bp,
        "reversed_commission_cents": reversed_commission_cents,
        "adjusted_gross_cents": adjusted_gross_cents,
        "tier_bonus_cents": adjusted_bonus_cents,
        "tax_withholding_cents": tax_withholding_cents,
        "final_payout_cents": final_payout_cents,
        "effective_sales_cents": effective_sales_cents,
    }


# ---------------------------------------------------------------------------
# Performance-tier ladder — calc_performance_tier
# ---------------------------------------------------------------------------

PLATINUM_GMV_CENTS = 50_000_000
GOLD_GMV_CENTS = 10_000_000
SILVER_GMV_CENTS = 1_000_000
DEMOTION_VIOLATION_SCORE = 50


def calc_performance_tier(*, lifetime_gmv_cents: int,
                          violation_score: int,
                          status: str) -> str:
    if violation_score >= DEMOTION_VIOLATION_SCORE or status == "BLACKLISTED":
        return "BRONZE"
    if lifetime_gmv_cents >= PLATINUM_GMV_CENTS and violation_score <= 5:
        return "PLATINUM"
    if lifetime_gmv_cents >= GOLD_GMV_CENTS and violation_score <= 10:
        return "GOLD"
    if lifetime_gmv_cents >= SILVER_GMV_CENTS and violation_score <= 20:
        return "SILVER"
    return "BRONZE"


# ---------------------------------------------------------------------------
# Refund calculation — calc_refund
# ---------------------------------------------------------------------------

FULL_REFUND_LEAD_HOURS = 72
PARTIAL_REFUND_LEAD_HOURS = 24


def calc_refund(*, starts_at: datetime, deposit_due_cents: int) -> int:
    lead_seconds = (starts_at - clock.now()).total_seconds()
    lead_hours = lead_seconds / 3600.0
    if lead_hours >= FULL_REFUND_LEAD_HOURS:
        return int(deposit_due_cents)
    if lead_hours >= PARTIAL_REFUND_LEAD_HOURS:
        return _round_half_up(Decimal(int(deposit_due_cents)) * Decimal("0.5"))
    return 0


# ---------------------------------------------------------------------------
# Violation penalty — calc_violation_penalty
# ---------------------------------------------------------------------------

SEVERITY_BY_TYPE = {
    "FALSE_ADVERTISING": 2,
    "WRONG_PRODUCT": 1,
    "VIOLATING_CONTENT": 3,
    "DATA_FRAUD": 4,
}
EVIDENCE_THRESHOLD = 3
BLACKLIST_SCORE = 100
SUSPENSION_SCORE = 50
SUSPENSION_DEFAULT_DAYS = 30
FINE_PER_SEVERITY_CENTS = 50_000


def calc_violation_penalty(*, violation_type: str,
                           evidence_refs_count: int,
                           current_violation_score: int) -> dict:
    base = SEVERITY_BY_TYPE[violation_type]
    bonus = 1 if evidence_refs_count >= EVIDENCE_THRESHOLD else 0
    severity = base + bonus
    score_after = current_violation_score + severity
    fine_cents = 0
    suspension_days = 0
    if score_after >= BLACKLIST_SCORE or (violation_type == "DATA_FRAUD" and severity >= 4):
        penalty_action = "BLACKLIST"
    elif score_after >= SUSPENSION_SCORE or severity >= 4:
        penalty_action = "SUSPENSION"
        suspension_days = SUSPENSION_DEFAULT_DAYS
    elif severity >= 2:
        penalty_action = "FINE"
        fine_cents = severity * FINE_PER_SEVERITY_CENTS
    else:
        penalty_action = "WARNING"
    return {
        "severity": severity,
        "penalty_action": penalty_action,
        "fine_cents": fine_cents,
        "suspension_days": suspension_days,
    }
