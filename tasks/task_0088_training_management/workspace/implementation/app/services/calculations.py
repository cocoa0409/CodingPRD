"""Calculation rules: credit awards, instructor fees, exam scores, evaluations, credit pools."""
from __future__ import annotations

import math
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Optional

from ..numbers import round_half_up
from ..store import get_store


PASS_THRESHOLD = 70
TIER_1_MAX = Decimal("2.0")
TIER_2_MAX = Decimal("5.0")
TIER_1_MULT = Decimal("1.00")
TIER_2_MULT = Decimal("0.95")
TIER_3_MULT = Decimal("0.90")
TIME_TRIGGER = 0.25
CREDIT_TRIGGER = 0.5


def attendance_factor(attendance_status: str) -> Decimal:
    if attendance_status == "PRESENT":
        return Decimal("1.0")
    if attendance_status == "PARTIAL":
        return Decimal("0.5")
    return Decimal("0.0")  # ABSENT or NOT_RECORDED


def exam_factor(exam_attempt: Optional[dict[str, Any]], attendance_status: str) -> Decimal:
    if exam_attempt is not None and exam_attempt.get("submitted_at"):
        if exam_attempt.get("passed", False):
            return Decimal("1.0")
        return Decimal("0.5")
    # missing exam (no submitted attempt)
    if attendance_status == "ABSENT":
        return Decimal("0.0")
    return Decimal("0.0")  # treated as fail


def compute_provisional_credit(credit_value: float, attendance_status: str) -> float:
    cv = Decimal(str(credit_value or 0))
    af = attendance_factor(attendance_status)
    raw = cv * af
    return float(raw.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def compute_final_credit(credit_value: float, attendance_status: str, exam_attempt: Optional[dict[str, Any]]) -> float:
    cv = Decimal(str(credit_value or 0))
    af = attendance_factor(attendance_status)
    if attendance_status == "ABSENT":
        return float(Decimal("0.0").quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))
    ef = exam_factor(exam_attempt, attendance_status)
    raw = cv * af * ef
    return float(raw.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def compute_instructor_fee(
    duration_hours: float,
    hourly_rate: float,
    travel_cost: float,
    instructor_type: str,
) -> dict[str, Any]:
    """Pin evaluation order per scaffold:
    1) effective_hours = ceil(duration_hours * 2) / 2  -> round up to nearest half-hour
    2) tier multiplier on effective_hours
    3) base_fee = round(hourly_rate * effective_hours * tier, 2)
    4) external: total = base_fee + travel_cost; internal: total = 0
    """
    # 1) effective_hours
    dh = Decimal(str(duration_hours or 0))
    # Round up to nearest half-hour: ceil(dh*2)/2
    doubled = dh * Decimal(2)
    ceil_int = Decimal(int(math.ceil(doubled)))  # math.ceil works on Decimal-like
    effective_hours = ceil_int / Decimal(2)

    # 2) tier multiplier
    if effective_hours >= Decimal("0.5") and effective_hours <= TIER_1_MAX:
        tier_mult = TIER_1_MULT
    elif effective_hours > TIER_1_MAX and effective_hours <= TIER_2_MAX:
        tier_mult = TIER_2_MULT
    else:
        tier_mult = TIER_3_MULT

    # 3) base_fee
    hr = Decimal(str(hourly_rate or 0))
    base_raw = hr * effective_hours * tier_mult
    base_fee = base_raw.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    # 4) total
    if instructor_type == "EXTERNAL":
        tc = Decimal(str(travel_cost or 0))
        total = base_fee + tc
    else:
        total = Decimal("0.00")

    return {
        "effective_hours": float(effective_hours),
        "tier_multiplier": float(tier_mult),
        "base_fee": float(base_fee.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "travel_cost": float(Decimal(str(travel_cost or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)) if instructor_type == "EXTERNAL" else 0.0,
        "total": float(total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "instructor_type": instructor_type,
    }


def compute_exam_score(questions: list[dict[str, Any]]) -> tuple[float, bool, int]:
    """Compute exam score percentage and pass flag.

    Returns (score, passed, total_weight).
    """
    total_weight = sum(int(q.get("weight", 0)) for q in questions)
    if total_weight == 0:
        return 0.0, False, 0
    correct_weight = sum(
        int(q.get("weight", 0))
        for q in questions
        if q.get("given_answer") is not None and q.get("given_answer") == q.get("correct_answer")
    )
    raw = (Decimal(correct_weight) / Decimal(total_weight)) * Decimal(100)
    score = float(raw.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    passed = score >= PASS_THRESHOLD
    return score, passed, total_weight


def compute_evaluation_aggregate(content_score: int, instructor_score: int, logistics_score: int) -> float:
    raw = Decimal("0.4") * Decimal(int(content_score)) + Decimal("0.3") * Decimal(int(instructor_score)) + Decimal("0.3") * Decimal(int(logistics_score))
    return float(raw.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def recompute_credit_pool_accumulated(pool: dict[str, Any]) -> None:
    """Sum final_credit for matching enrollments + adjustment deltas. Write into pool['accumulated_credits']."""
    store = get_store()
    trainee_id = pool["trainee_id"]
    cycle_start = pool["cycle_start"]
    cycle_end = pool["cycle_end"]

    # Use parse_iso for comparisons
    from ..clock import parse_iso

    cs = parse_iso(cycle_start)
    ce = parse_iso(cycle_end)

    total = Decimal("0")
    for e in store.enrollments.values():
        if e["trainee_id"] != trainee_id:
            continue
        if e["status"] not in ("COMPLETED", "FAILED"):
            continue
        sess = store.sessions.get(e["session_id"])
        if not sess:
            continue
        sa = parse_iso(sess["start_at"])
        if cs <= sa < ce:
            total += Decimal(str(e.get("final_credit", 0)))

    for adj in store.credit_adjustments.values():
        if adj["credit_pool_id"] == pool["id"]:
            total += Decimal(str(adj.get("delta", 0)))

    rounded = total.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    pool["accumulated_credits"] = float(rounded)


def recompute_instructor_avg_eval(instructor_id: str) -> None:
    """Average EvaluationSurvey.aggregate_score for completed enrollments of this instructor's sessions."""
    store = get_store()
    scores: list[Decimal] = []
    # Find sessions for this instructor that are COMPLETED, collect their enrollments,
    # then find EvaluationSurveys referencing those enrollments.
    completed_session_ids = {
        s["id"] for s in store.sessions.values()
        if s.get("instructor_id") == instructor_id and s.get("status") == "COMPLETED"
    }
    enr_ids = {
        e["id"] for e in store.enrollments.values()
        if e.get("session_id") in completed_session_ids
    }
    for ev in store.evaluations.values():
        if ev.get("enrollment_id") in enr_ids:
            scores.append(Decimal(str(ev.get("aggregate_score", 0))))
    inst = store.instructors.get(instructor_id)
    if inst is None:
        return
    if not scores:
        inst["avg_evaluation_score"] = None
        return
    total = sum(scores, Decimal(0))
    avg = (total / Decimal(len(scores))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    inst["avg_evaluation_score"] = float(avg)


def evaluate_shortfall_warning(pool: dict[str, Any], now_dt) -> bool:
    """Returns True iff warning was emitted (and flag flipped)."""
    if pool.get("shortfall_warning_emitted"):
        return False
    from ..clock import parse_iso
    cs = parse_iso(pool["cycle_start"])
    ce = parse_iso(pool["cycle_end"])
    if now_dt >= ce or now_dt < cs:
        # outside the cycle window
        return False
    full_span = (ce - cs).total_seconds()
    remaining = (ce - now_dt).total_seconds()
    if full_span <= 0:
        return False
    time_fraction_remaining = remaining / full_span
    req = float(pool.get("required_credits") or 0)
    if req <= 0:
        return False
    credit_fraction = float(pool.get("accumulated_credits", 0)) / req
    if time_fraction_remaining <= TIME_TRIGGER and credit_fraction < CREDIT_TRIGGER:
        pool["shortfall_warning_emitted"] = True
        return True
    return False
