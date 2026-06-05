"""Calculation rules (scaffold §1.3, PRD §3.3 / §3.4 / §3.5 / §3.7 / §3.8).

Every helper here is pure — it reads from db.* stores or the supplied entity
dict and returns the computed value. State mutation (writes to the entity
dict, version bumps, status flips) is performed by the cascade layer in
services/cascades.py, not here.
"""
from __future__ import annotations

import math
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, Any, List

import db


# ---- Eight-minute rule (PRD §3.3 / §3.5; scaffold §1.3 evaluation_units,
#       visit_planned_units, visit_billable_units) ----


def eight_minute_units(minutes: int) -> int:
    """CMS 8-minute rule on a single session's minutes.

    Buckets (inclusive):  <8 -> 0; 8..22 -> 1; 23..37 -> 2; 38..52 -> 3;
    53..67 -> 4; >=68 -> ceil((m-7)/15).

    The same step function is used for evaluation_units (on minutes_spent),
    visit_planned_units (on planned_minutes, forward-looking variant) and
    visit_billable_units (on actual_minutes, chronological variant) — the
    scaffold's "dual variant" is the same arithmetic over different inputs.
    """
    m = minutes
    if m < 8:
        return 0
    if m <= 22:
        return 1
    if m <= 37:
        return 2
    if m <= 52:
        return 3
    if m <= 67:
        return 4
    return math.ceil((m - 7) / 15)


# ---- Visit billed amount + MPPR (PRD §3.5; scaffold §1.3 visit_billed_amount)


CPT_RATE_CENTS: Dict[str, int] = {
    "CPT_97110_THER_EX": 3200,
    "CPT_97112_NEURO_REED": 3900,
    "CPT_97140_MANUAL": 3500,
    "CPT_97530_THER_ACT": 3700,
}


def _round_half_up_int(value: Decimal) -> int:
    """Round a Decimal half-up to the nearest integer (no negative-zero quirk)."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def visit_billed_cents(cpt_code: str, billable_units: int) -> int:
    """Multiple-procedure payment reduction (MPPR) per PRD §3.5.

    First unit at the full per-CPT rate; every unit beyond the first at a
    reduced per-unit rate = rate * 0.5, rounded half-up PER UNIT before being
    multiplied by the count of reduced units. Order is round-per-unit-then-sum.
    """
    if billable_units <= 0:
        return 0
    rate = CPT_RATE_CENTS[cpt_code]
    if billable_units == 1:
        return rate
    first_unit = rate
    extra_units = billable_units - 1
    reduced_per_unit = _round_half_up_int(Decimal(rate) * Decimal("0.5"))
    return first_unit + reduced_per_unit * extra_units


# ---- Capped Plan of Care (PRD §2.7 / §3.5; scaffold §1.3 capped_poc_limit /
#       capped_poc_posture) ----


CAPPED_LIMITS_CENTS: Dict[str, int] = {
    "MEDICARE": 20000,
    "COMMERCIAL": 50000,
    "MEDICAID": 10000,
    "VA_TRICARE": 30000,
    "SELF_PAY": 100000,
}


def capped_dollar_limit_cents(insurance_type: str) -> int:
    return CAPPED_LIMITS_CENTS[insurance_type]


def capped_posture(cumulative_cents: int, limit_cents: int) -> str:
    """Three-bucket posture from PRD §2.7.

      UNDER_CAP       when cumulative < 0.90 * limit
      AT_CAP_WARNING  when 0.90 * limit <= cumulative <= limit   (lower bound inclusive)
      EXCEEDED        when cumulative > limit                    (strictly over)
    """
    if cumulative_cents > limit_cents:
        return "EXCEEDED"
    # Compare with integer arithmetic to avoid float-comparison surprises at
    # the boundary: cumulative >= 0.90 * limit  <=>  cumulative * 100 >= limit * 90.
    if cumulative_cents * 100 >= limit_cents * 90:
        return "AT_CAP_WARNING"
    return "UNDER_CAP"


# ---- Aggregations (scaffold §1.3 units_consumed_running,
#       units_finalized_running, cumulative_billed) ----


def grant_units_consumed(grant_id: str) -> int:
    """Sum planned_units (SCHEDULED) + billable_units (COMPLETED/FINALIZED)
    over visits on this grant, ordered by (created_at, id)."""
    eligible: List[Dict[str, Any]] = [
        v
        for v in db.visits.values()
        if v["authorization_grant_id"] == grant_id
        and v["status"] in {"SCHEDULED", "COMPLETED", "FINALIZED"}
    ]
    eligible.sort(key=db.created_then_id)
    total = 0
    for v in eligible:
        if v["status"] == "SCHEDULED":
            total += v.get("planned_units", 0) or 0
        else:
            total += v.get("billable_units", 0) or 0
    return total


def grant_units_finalized(grant_id: str) -> int:
    eligible = [
        v
        for v in db.visits.values()
        if v["authorization_grant_id"] == grant_id and v["status"] == "FINALIZED"
    ]
    eligible.sort(key=db.created_then_id)
    return sum((v.get("billable_units", 0) or 0) for v in eligible)


def poc_cumulative_billed_cents(poc_id: str) -> int:
    """Sum billed_cents across every FINALIZED visit reachable via any grant
    of this POC, ordered by (created_at, id)."""
    grant_ids = {
        g["id"] for g in db.authorization_grants.values() if g["plan_of_care_id"] == poc_id
    }
    finalized = [
        v
        for v in db.visits.values()
        if v["authorization_grant_id"] in grant_ids and v["status"] == "FINALIZED"
    ]
    finalized.sort(key=db.created_then_id)
    return sum((v.get("billed_cents", 0) or 0) for v in finalized)


# ---- MIPS composite score (PRD §3.7; scaffold §1.3 mips_composite_score) ----


MIPS_BASE_SCORES: Dict[str, float] = {
    "MIPS128_FALL_RISK": 60.0,
    "MIPS131_PAIN_ASSESSMENT": 18.0,
    "MIPS182_FUNCTIONAL_OUTCOME": 70.0,
}


def _round_half_up_two_dp(value: Decimal) -> float:
    """Round a Decimal half-up to two decimal places, return float."""
    q = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(q)


def mips_composite_score(measure: Dict[str, Any]) -> float:
    """Weighted scoring per PRD §3.7.

    base + numerator_bonus + engagement + improvement_bonus, capped at 100.0,
    rounded half-up to two decimal places.
    """
    base = MIPS_BASE_SCORES[measure["measure_code"]]
    numerator_bonus = 25.0 if measure["numerator_met"] else 0.0

    poc_id = measure["plan_of_care_id"]
    period_start = measure["performance_period_start"]
    period_end = measure["performance_period_end"]

    # Engagement = ACTIVE HEPs under same POC with prescribed_on in [start, end]
    hep_count = 0
    for hep in db.home_exercise_programs.values():
        if hep["plan_of_care_id"] != poc_id:
            continue
        if hep["status"] != "ACTIVE":
            continue
        if hep["prescribed_on"] < period_start or hep["prescribed_on"] > period_end:
            continue
        hep_count += 1
    engagement = min(10.0, hep_count * 3.5)

    # Functional improvement = latest_eval.functional_score - initial_eval.functional_score
    # (clamped at 0). Latest evaluation on the POC ordered by (performed_on, created_at).
    poc_evals: List[Dict[str, Any]] = [
        e for e in db.evaluations.values() if e["plan_of_care_id"] == poc_id
    ]
    initial_eval = next(
        (e for e in poc_evals if e["evaluation_kind"] == "INITIAL"), None
    )
    if initial_eval is None or not poc_evals:
        improvement = 0
    else:
        latest_sorted = sorted(
            poc_evals, key=lambda e: (e["performed_on"], e["created_at"])
        )
        latest_eval = latest_sorted[-1]
        improvement = max(
            0, latest_eval["functional_score"] - initial_eval["functional_score"]
        )
    improvement_bonus = min(15.0, improvement * 0.5)

    raw = base + numerator_bonus + engagement + improvement_bonus
    capped = min(100.0, raw)
    return _round_half_up_two_dp(Decimal(str(capped)))


# ---- Discharge outcome (PRD §3.8; scaffold §1.3 discharge_outcome) ----


def discharge_outcome(goals_met: int, total_goals: int) -> str:
    """Bucket the goals-met ratio."""
    # total_goals_count is guaranteed >= 1 by §1.1 constraints and rejected
    # earlier if violated; defensive zero-check here regardless.
    if total_goals <= 0:
        return "UNSUCCESSFUL"
    ratio = goals_met / total_goals
    if ratio >= 0.80:
        return "SUCCESSFUL"
    if ratio >= 0.40:
        return "PARTIAL"
    return "UNSUCCESSFUL"
