"""Calculation rules per scaffold §1.3.

Includes:
  - participant_eligibility_score (forward-looking & chronological variants)
  - participant_compensation (provisional & final variants)
  - arm_assignment (SIMPLE_BERNOULLI / PERMUTED_BLOCK / STRATIFIED_BLOCK)
  - blood_draw_window_check
"""
from __future__ import annotations

from datetime import datetime, date, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from ..errors import (
    err_invalid_input,
    err_no_arms_defined,
    err_stratum_key_missing,
)


# ---- Compensation constants (cents) per scaffold §1.3 -------------------

BASE_VISIT_CENTS = 5000
ON_TIME_BONUS_CENTS = 1000
LATE_PENALTY_CENTS = 750
RE_CONSENT_BONUS_CENTS = 2500

ELIGIBILITY_THRESHOLD = Decimal("80.0")


# =========================================================================
# Eligibility score
# =========================================================================

def _eval_predicate(predicate: dict[str, Any], profile: dict[str, Any]) -> tuple[bool, bool]:
    """Evaluate one inclusion/exclusion predicate against a profile.

    Returns (field_present, matches).
    """
    if not isinstance(predicate, dict):
        return (False, False)
    field = predicate.get("field")
    op = predicate.get("op")
    value = predicate.get("value")
    if not isinstance(field, str) or field not in profile:
        return (False, False)
    pv = profile[field]
    try:
        if op == "EQ":
            return (True, pv == value)
        if op == "GTE":
            return (True, pv >= value)
        if op == "LTE":
            return (True, pv <= value)
        if op == "IN":
            if not isinstance(value, list):
                return (True, False)
            return (True, pv in value)
        if op == "BETWEEN":
            if not isinstance(value, list) or len(value) != 2:
                return (True, False)
            lo, hi = value
            return (True, lo <= pv <= hi)
    except TypeError:
        # Mixed-type comparisons (e.g., str vs int) — treat as non-match.
        return (True, False)
    return (False, False)


def compute_eligibility(
    profile: dict[str, Any],
    inclusion_criteria: list[dict[str, Any]],
    exclusion_criteria: list[dict[str, Any]],
) -> tuple[str, float]:
    """Returns (decision, score).

    Step 1 (exclusion gate): any exclusion predicate matching → INELIGIBLE, score=0.0.
    Step 2 (inclusion score): sum of 1-per-match, divided by count, scaled to percentage.
    Step 3: score >= ELIGIBILITY_THRESHOLD → ELIGIBLE else INELIGIBLE.
    """
    profile = profile or {}

    # Step 1: exclusion gate
    for pred in exclusion_criteria or []:
        present, matches = _eval_predicate(pred, profile)
        if present and matches:
            return ("INELIGIBLE", 0.0)

    # Step 2: inclusion contributions
    incl = inclusion_criteria or []
    if not incl:
        # No inclusion criteria → score is 0/0; treat fraction as 0 → INELIGIBLE.
        return ("INELIGIBLE", 0.0)
    contributions = 0
    for pred in incl:
        present, matches = _eval_predicate(pred, profile)
        if present and matches:
            contributions += 1

    raw = (Decimal(100) * Decimal(contributions) / Decimal(len(incl)))
    score = raw.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    decision = "ELIGIBLE" if score >= ELIGIBILITY_THRESHOLD else "INELIGIBLE"
    return (decision, float(score))


# =========================================================================
# Blood-draw window check
# =========================================================================

def _to_utc_date(value: Any) -> date:
    """Convert a datetime / str to a UTC calendar date (time-of-day dropped after normalization)."""
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        return value
    elif isinstance(value, str):
        raw = value.strip()
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(raw)
        except ValueError:
            raise err_invalid_input("invalid ISO 8601 timestamp")
    else:
        raise err_invalid_input("expected ISO 8601 timestamp")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.date()


def day_offset(actual_draw_at: Any, target_date: Any) -> int:
    """abs((actual_draw_at::date) - (target_date::date)) in whole calendar days."""
    a = _to_utc_date(actual_draw_at)
    t = _to_utc_date(target_date)
    return abs((a - t).days)


def within_window(actual_draw_at: Any, target_date: Any, window_days: int) -> bool:
    return day_offset(actual_draw_at, target_date) <= window_days


# =========================================================================
# Per-visit compensation
# =========================================================================

def visit_provisional_cents(actual_draw_at: Any, target_date: Any, window_days: int) -> int:
    """Per-visit compensation in cents, provisional variant per scaffold §1.3."""
    d = day_offset(actual_draw_at, target_date)
    if d == 0:
        bonus = ON_TIME_BONUS_CENTS
    elif 1 <= d <= 2:
        bonus = 0
    elif 3 <= d <= window_days:
        bonus = -LATE_PENALTY_CENTS * (d - 2)
    else:
        # Out of window — caller should have rejected before reaching this point.
        bonus = -BASE_VISIT_CENTS
    # Clamp the bonus so net never falls below zero.
    if bonus < -BASE_VISIT_CENTS:
        bonus = -BASE_VISIT_CENTS
    provisional = BASE_VISIT_CENTS + bonus
    if provisional < 0:
        provisional = 0
    return provisional


# =========================================================================
# Arm assignment
# =========================================================================

def assign_arm(
    randomization_scheme: str,
    arms: list[dict[str, Any]],
    block_size: int | None,
    stratification_field: str | None,
    profile: dict[str, Any],
    trial_enrolled_count: int,
    stratum_counters: dict[str, int],
) -> dict[str, Any]:
    """Deterministically pick an arm. See PRD §3.5.

    `arms` is the full list of Arm rows on the trial (any order).
    `trial_enrolled_count` is the count BEFORE this enrollment commits.
    `stratum_counters` is a {stratum_key → count_before_this_enrollment} dict.
    """
    if not arms:
        raise err_no_arms_defined()

    if randomization_scheme == "SIMPLE_BERNOULLI":
        # Pick the arm with smallest assigned_count / weight; tie-break by lexicographic code.
        def key(a: dict[str, Any]) -> tuple[Any, str]:
            # Use Decimal for exact ordering; avoids float rounding surprises.
            ratio = Decimal(a["assigned_count"]) / Decimal(a["weight"])
            return (ratio, a["code"])

        return min(arms, key=key)

    if randomization_scheme in {"PERMUTED_BLOCK", "STRATIFIED_BLOCK"}:
        # Order arms by code ascending.
        ordered = sorted(arms, key=lambda a: a["code"])
        n = len(ordered)
        if block_size is None or n == 0 or block_size % n != 0:
            # Defensive — submit-for-irb should have caught this.
            raise err_no_arms_defined("block_size not divisible by arm count")
        per_arm = block_size // n
        # Build the canonical block sequence: [code0]*per_arm + [code1]*per_arm + ...
        sequence: list[dict[str, Any]] = []
        for arm in ordered:
            sequence.extend([arm] * per_arm)
        if randomization_scheme == "PERMUTED_BLOCK":
            pos_within_block = trial_enrolled_count % block_size
        else:  # STRATIFIED_BLOCK
            if not stratification_field or stratification_field not in (profile or {}):
                raise err_stratum_key_missing()
            stratum_key = str(profile[stratification_field])
            counter = stratum_counters.get(stratum_key, 0)
            pos_within_block = counter % block_size
        return sequence[pos_within_block]

    raise err_invalid_input(f"Unknown randomization_scheme: {randomization_scheme}")
