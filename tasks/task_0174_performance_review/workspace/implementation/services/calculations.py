"""Calculation primitives (SCAFFOLD §1.3 and PRD §3.7, §2.9).

Pinned rules:
- Weighted goal score: sum(weight_i * manager_score_i) / 100, round_half_up to 2dp.
- Merit increase: integer cents, per-line floor; PROMO_BUMP_PCT 5 added if promo & top ratings;
  ON_PIP forces zero; SEMI_ANNUAL halves the percentage via floor.
- Equity refresh: multiplier first then round_half_up, then add already-rounded promo bump
  (which is itself floor of 0.25 * NEXT-level grant for same rating). ON_PIP forces zero.
- Bell-curve compliance: floor(100 * count / total) per bucket, tolerance 5 pp.
"""

from decimal import ROUND_HALF_UP, Decimal
from typing import Dict, List, Optional

import config


def round_half_up_int(value: float) -> int:
    """Round half-up to nearest integer using Decimal to avoid IEEE-754 surprises."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_2dp(value: float) -> float:
    """Round half-up to two decimal places."""
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def equity_grant_for_level(job_level: int) -> Dict[str, int]:
    """Return the equity grant row keyed by rating for the given job_level band."""
    if 1 <= job_level <= 3:
        return config.EQUITY_GRANT_LEVELS_1_3
    if 4 <= job_level <= 6:
        return config.EQUITY_GRANT_LEVELS_4_6
    if 7 <= job_level <= 10:
        return config.EQUITY_GRANT_LEVELS_7_10
    # Fall back to zeros for out-of-range levels (input is gated elsewhere).
    return {r: 0 for r in config.RATING_BUCKETS}


# -----------------------------------------------------------------------------
# Weighted goal score
# -----------------------------------------------------------------------------

def weighted_goal_score(goals: List[dict]) -> float:
    """Canonical formula: sum(weight_i * manager_score_i) / 100, round_half_up 2dp.

    Evaluates goals in ascending created_at order for deterministic accumulation.
    Treats null manager_score as 0 — submission validates that all scores are set.
    """
    if not goals:
        return 0.0
    ordered = sorted(goals, key=lambda g: g["created_at"])
    total = Decimal("0")
    for g in ordered:
        w = g.get("weight") or 0
        ms = g.get("manager_score")
        if ms is None:
            ms = 0
        total += Decimal(int(w)) * Decimal(int(ms))
    val = total / Decimal("100")
    return float(val.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


# -----------------------------------------------------------------------------
# Merit increase
# -----------------------------------------------------------------------------

def merit_increase_cents(
    pinned_base_salary_cents: int,
    final_rating: Optional[str],
    cadence: str,
    promotion_to_level: Optional[int],
    employee_status: str,
    current_job_level: int,
) -> int:
    """Implements the merit_increase_amount calculation (SCAFFOLD §1.3, PRD §3.7).

    Cadence-driven base table:
      ANNUAL    -> base pct = MERIT_PCT[rating]
      SEMI_ANNUAL -> floor(MERIT_PCT[rating] / 2)
    raw = floor(pinned_base_salary_cents * pct / 100)
    Promotion bump (only if promotion_to_level set AND rating in {OUTSTANDING, EXCEEDS}):
      bump = floor(pinned_base_salary_cents * PROMO_BUMP_PCT / 100)
    PIP gate forces zero.
    """
    if final_rating is None:
        return 0

    base_pct = config.MERIT_PCT.get(final_rating, 0)
    if cadence == "SEMI_ANNUAL":
        # "Every cell of BMA divided by 2, floor of cents" — for percentages,
        # the directive is integer floor of the cell.
        base_pct = base_pct // 2

    raw = (pinned_base_salary_cents * base_pct) // 100  # integer floor

    if (
        promotion_to_level is not None
        and final_rating in ("OUTSTANDING", "EXCEEDS")
        and employee_status == "ACTIVE"
        # PIP gate would zero this anyway, but ACTIVE-only short-circuits early.
    ):
        bump = (pinned_base_salary_cents * config.PROMO_BUMP_PCT) // 100
        raw += bump

    if employee_status == "ON_PIP":
        return 0

    return int(raw)


# -----------------------------------------------------------------------------
# Equity refresh
# -----------------------------------------------------------------------------

def equity_refresh_units(
    final_rating: Optional[str],
    job_level: int,
    cadence: str,
    promotion_to_level: Optional[int],
    employee_status: str,
) -> int:
    """Implements equity_refresh_amount (SCAFFOLD §1.3 / PRD §3.7).

    Pinned order:
      base_units = grant_units_table[job_level][final_rating]
      base_rounded = round_half_up( base_units * multiplier )
      bump = floor( grant_units_table[promotion_to_level][final_rating] * 0.25 )
             (only when promotion_to_level set AND rating IN {OUTSTANDING, EXCEEDS}
              AND employee status == ACTIVE — promo is blocked on PIP elsewhere)
      total = base_rounded + bump  (sum AFTER each is independently rounded)
      if employee_status == ON_PIP: total = 0
    """
    if final_rating is None:
        return 0

    base_units = equity_grant_for_level(job_level).get(final_rating, 0)
    multiplier = (
        config.MULT_ANNUAL if cadence == "ANNUAL" else config.MULT_SEMI_ANNUAL
    )
    base_rounded = round_half_up_int(base_units * multiplier)

    bump = 0
    if (
        promotion_to_level is not None
        and final_rating in ("OUTSTANDING", "EXCEEDS")
        and employee_status == "ACTIVE"
    ):
        next_grant = equity_grant_for_level(promotion_to_level).get(final_rating, 0)
        # floor of 0.25 * next-level grant
        bump = int((next_grant * 25) // 100)

    total = base_rounded + bump

    if employee_status == "ON_PIP":
        return 0

    return int(total)


# -----------------------------------------------------------------------------
# Bell-curve compliance
# -----------------------------------------------------------------------------

def bell_curve_distribution(proposed_ratings: List[dict]) -> Dict[str, int]:
    """Five-bucket histogram. Each entry of proposed_ratings is a
    {review_case_id, proposed_rating} dict."""
    dist = {b: 0 for b in config.RATING_BUCKETS}
    for entry in proposed_ratings or []:
        r = entry.get("proposed_rating")
        if r in dist:
            dist[r] += 1
    return dist


def bell_curve_compliance(
    proposed_ratings: List[dict], target: Dict[str, int]
) -> Dict[str, list]:
    """Returns {'compliant': bool, 'offending': [bucket, ...]}. Floor-based percent."""
    total = len(proposed_ratings or [])
    offending = []
    if total == 0:
        # No work to do: vacuously compliant; coverage rule will fail upstream.
        return {"compliant": True, "offending": []}
    dist = bell_curve_distribution(proposed_ratings)
    for bucket in config.RATING_BUCKETS:
        observed_pct = (100 * dist[bucket]) // total  # floor
        target_pct = int(target.get(bucket, 0))
        if abs(observed_pct - target_pct) > config.BELL_CURVE_TOLERANCE_PP:
            offending.append(bucket)
    return {"compliant": not offending, "offending": offending}
