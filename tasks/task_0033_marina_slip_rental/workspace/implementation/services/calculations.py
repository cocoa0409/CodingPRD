"""Calculation rules (scaffold §1.3 / PRD §3.5, §3.6, §3.7, §3.8).

All monetary values are integer cents. Where a multiplication produces a
fractional cent, half-up rounding is applied at each rounding step.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict


# Constants from scaffold §1.3
SEASONAL_MULTIPLIER_SUMMER_NUM = 150
SEASONAL_MULTIPLIER_SUMMER_DEN = 100
SEASONAL_MULTIPLIER_WINTER_NUM = 80
SEASONAL_MULTIPLIER_WINTER_DEN = 100
LIVEABOARD_SURCHARGE_NUM = 110
LIVEABOARD_SURCHARGE_DEN = 100
LIVEABOARD_UTILITY_FEE_PER_NIGHT_CENTS = 1500
PUMPOUT_PORTABLE_FEE_CENTS = 2500
MIN_INSURANCE_COVERAGE_CENTS = 5_000_000  # $50,000 in cents

# Waitlist time-to-live for the expire-stale sweep.
WAITLIST_TTL_DAYS = 30


def _half_up(num: int, den: int) -> int:
    """Multiply an integer-cents value already encoded as `num` by 1/den,
    rounding half-up to the nearest integer.

    Note: callers compute `cents * multiplier_num` first as a Python int (no
    precision loss), then pass that as `num` with `den = multiplier_den`.
    """
    if den <= 0:
        raise ValueError("denominator must be positive")
    q = Decimal(num) / Decimal(den)
    return int(q.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _mmdd_in_summer(start_date: date, summer_start: tuple, summer_end: tuple) -> bool:
    """Per PRD §3.5: SUMMER iff Lease.start_date (month-day component) lies
    on or between season_summer_start and season_summer_end inclusive.

    summer_start / summer_end are (month, day) tuples.
    """
    md = (start_date.month, start_date.day)
    # Compare month-day tuples lexicographically; works regardless of leap year
    # because we only compare month-day components.
    return summer_start <= md <= summer_end


def seasonal_lease_pricing(
    base_daily_rate_cents: int,
    is_liveaboard: bool,
    start_date: date,
    summer_start: tuple,
    summer_end: tuple,
) -> int:
    """Pin Lease.nightly_rate_cents per scaffold seasonal_lease_pricing.

    Step 1: pick seasonal multiplier from start_date month-day window.
    Step 2: nightly = round_half_up(base * seasonal_mul).
    Step 3: nightly = round_half_up(nightly * liveaboard_mul).
    """
    if _mmdd_in_summer(start_date, summer_start, summer_end):
        s_num, s_den = SEASONAL_MULTIPLIER_SUMMER_NUM, SEASONAL_MULTIPLIER_SUMMER_DEN
    else:
        s_num, s_den = SEASONAL_MULTIPLIER_WINTER_NUM, SEASONAL_MULTIPLIER_WINTER_DEN

    # Step 2 — round half up after seasonal multiplier.
    step2 = _half_up(base_daily_rate_cents * s_num, s_den)

    # Step 3 — surcharge multiplier (1.10 for liveaboard, 1.00 otherwise),
    # round half up independently after the second multiplication.
    if is_liveaboard:
        l_num, l_den = LIVEABOARD_SURCHARGE_NUM, LIVEABOARD_SURCHARGE_DEN
    else:
        l_num, l_den = 100, 100  # 1.00 — no-op but still goes through the same path
    nightly = _half_up(step2 * l_num, l_den)
    return nightly


def lease_total_cost(
    nights: int,
    nightly_rate_cents: int,
    is_liveaboard: bool,
) -> int:
    """Pin Lease.total_cost_cents per scaffold lease_total_cost.

    total = nights * nightly_rate_cents
            + (LIVEABOARD_UTILITY_FEE_PER_NIGHT_CENTS * nights if is_liveaboard).
    """
    base = nights * nightly_rate_cents
    surcharge = LIVEABOARD_UTILITY_FEE_PER_NIGHT_CENTS * nights if is_liveaboard else 0
    return base + surcharge


def pumpout_charge(slip_pumpout_available: bool) -> int:
    """Pin PumpOutRequest.charge_cents per scaffold pumpout_charge."""
    return 0 if slip_pumpout_available else PUMPOUT_PORTABLE_FEE_CENTS


def insurance_valid(vessel: Dict, today_utc: date) -> bool:
    """Insurance VALID iff insurance_expires_on is strictly after today_utc
    AND insurance_coverage_cents >= MIN_INSURANCE_COVERAGE_CENTS.

    Per scaffold Vessel.insurance_expires_on description:
      "Insurance is considered VALID for any clock instant strictly less than
       YYYY-MM-DDT00:00:00Z of this date".
    Combined with PRD §3.5 / §3.7's requirement that insurance_coverage_cents
    must be >= MIN_INSURANCE_COVERAGE_CENTS at check-in / tow dispatch.
    """
    expires_str = vessel.get("insurance_expires_on")
    coverage = vessel.get("insurance_coverage_cents", 0)
    try:
        from datetime import date as _date
        # The stored value is always a YYYY-MM-DD string we validated on create.
        expires = _date.fromisoformat(expires_str)
    except (ValueError, TypeError):
        return False
    if not (expires > today_utc):
        return False
    if coverage < MIN_INSURANCE_COVERAGE_CENTS:
        return False
    return True


def tow_assistance_outcome(
    vessel: Dict, marina: Dict, incident_distance_nm: float, today_utc: date
) -> str:
    """Synchronous tow-assist evaluation per scaffold tow_assistance_dispatch
    and PRD §3.7.

    Evaluation order is FIXED:
      step 1 — insurance (short-circuit on failure -> INSURANCE_INVALID)
      step 2 — radius   (failure -> OUT_OF_RADIUS)
      otherwise -> COVERED
    """
    if not insurance_valid(vessel, today_utc):
        return "INSURANCE_INVALID"
    if incident_distance_nm > float(marina.get("tow_assist_radius_nm", 0.0)):
        return "OUT_OF_RADIUS"
    return "COVERED"
