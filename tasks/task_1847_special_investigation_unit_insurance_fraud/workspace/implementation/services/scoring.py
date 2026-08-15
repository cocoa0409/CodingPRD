"""Calculation rules (SCAFFOLD §1.3 / PRD §3).

- red_flag_score: weighted sum + combination bonus, then high-value multiplier
  (round half-up), then band thresholds.
- substantiated_fraud_total: sum of ADMITTED + SUBSTANTIVE evidence amounts;
  bureau_referral_required derivation.
- provider_pattern_score: per-case weight + ring bonus + multi-state bonus +
  evidence-type diversity, capped at 100.
- bureau deadline / payment delay windows: per-state day tables, 86,400-second
  days, inclusive boundaries.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import db
from constants import (
    BAND_HIGH_MAX,
    BAND_LOW_MAX,
    BAND_MED_MAX,
    BUREAU_REFERRAL_MIN_CENTS,
    CODE_WEIGHT,
    COMBINATION_BONUS,
    COMBINATION_MIN_CODES,
    DEFAULT_BUREAU_WINDOW_DAYS,
    DEFAULT_DELAY_CAP_DAYS,
    EVIDENCE_DIVERSITY_WEIGHT,
    HIGH_VALUE_CLAIM_CENTS,
    HIGH_VALUE_MULTIPLIER,
    MANDATORY_REFERRAL_STATES,
    PATTERN_MAX_SCORE,
    PER_CASE_WEIGHT,
    RING_BONUS,
    RING_SIZE_THRESHOLD,
    MULTI_STATE_BONUS,
    SECONDS_PER_DAY,
    STATE_BUREAU_WINDOW_DAYS,
    STATE_DELAY_CAP_DAYS,
)


# ---------------------------------------------------------------------------
# red_flag_score
# ---------------------------------------------------------------------------


def compute_referral_score(red_flag_codes: list, claim: dict, modifier_overrides=None) -> tuple[int, str]:
    weights = dict(CODE_WEIGHT)
    if modifier_overrides:
        for code, weight in modifier_overrides.items():
            if code in weights and isinstance(weight, int) and not isinstance(weight, bool):
                weights[code] = weight
    score = 0
    for code in red_flag_codes:
        score += weights.get(code, 0)
    if len(red_flag_codes) >= COMBINATION_MIN_CODES:
        score += COMBINATION_BONUS
    if int(claim.get("claimed_amount_cents", 0)) >= HIGH_VALUE_CLAIM_CENTS:
        product = Decimal(score) * Decimal(HIGH_VALUE_MULTIPLIER)
        score = int(product.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return score, score_band(score)


def score_band(score: int) -> str:
    if score < BAND_LOW_MAX:
        return "LOW"
    if score < BAND_MED_MAX:
        return "MEDIUM"
    if score < BAND_HIGH_MAX:
        return "HIGH"
    return "CRITICAL"


# ---------------------------------------------------------------------------
# substantiated_fraud_total + bureau flag
# ---------------------------------------------------------------------------


def case_evidence(case_id: str) -> list:
    return [row for row in db.evidence.values() if row.get("case_id") == case_id]


def has_admitted_evidence(case_id: str) -> bool:
    return any(row.get("status") == "ADMITTED" for row in case_evidence(case_id))


def recompute_substantiated(case: dict) -> None:
    """Running total over ADMITTED + SUBSTANTIVE evidence; sealed evidence is
    excluded (it is no longer ADMITTED). Then recompute the bureau flag."""
    total = sum(
        int(row.get("fraud_amount_cents", 0))
        for row in case_evidence(case["id"])
        if row.get("status") == "ADMITTED" and row.get("materiality") == "SUBSTANTIVE"
    )
    case["substantiated_fraud_cents"] = total
    claim = db.claims.get(case.get("claim_id")) or {}
    state_code = claim.get("state_code")
    case["bureau_referral_required"] = bool(
        total >= BUREAU_REFERRAL_MIN_CENTS
        or (state_code in MANDATORY_REFERRAL_STATES and total > 0)
    )


# ---------------------------------------------------------------------------
# provider_pattern_score
# ---------------------------------------------------------------------------


def recompute_pattern_score(pattern: dict) -> None:
    linked_ids = pattern.get("linked_case_ids") or []
    linked_cases = [db.cases[cid] for cid in linked_ids if cid in db.cases]
    base = len(linked_cases) * PER_CASE_WEIGHT
    if len(linked_cases) >= RING_SIZE_THRESHOLD:
        base += RING_BONUS
    states = set()
    for case in linked_cases:
        claim = db.claims.get(case.get("claim_id"))
        if claim is not None:
            states.add(claim.get("state_code"))
    if len(states) >= 2:
        base += MULTI_STATE_BONUS
    evidence_types = set()
    for case in linked_cases:
        for row in case_evidence(case["id"]):
            if row.get("status") == "ADMITTED":
                evidence_types.add(row.get("evidence_type"))
    score = base + len(evidence_types) * EVIDENCE_DIVERSITY_WEIGHT
    pattern["pattern_score"] = min(score, PATTERN_MAX_SCORE)


# ---------------------------------------------------------------------------
# Statutory windows
# ---------------------------------------------------------------------------


def bureau_deadline(state_code: str, from_dt) -> object:
    days = STATE_BUREAU_WINDOW_DAYS.get(state_code, DEFAULT_BUREAU_WINDOW_DAYS)
    return from_dt + timedelta(days=days)


def delay_cap_until(state_code: str, from_dt) -> object:
    days = STATE_DELAY_CAP_DAYS.get(state_code, DEFAULT_DELAY_CAP_DAYS)
    return from_dt + timedelta(days=days)


def days_from_now(days: int):
    return db.clock.now + timedelta(seconds=days * SECONDS_PER_DAY)
