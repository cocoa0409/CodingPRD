"""Calculation routines per SCAFFOLD §1.3."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from config import (
    CHIEF_COMPLAINT_FACTOR,
    VITAL_ANOMALY_FACTOR,
    RISK_FACTOR,
    RISK_TABLE,
    VITAL_PREFIX,
    TIER1_CAP_MIN,
    TIER1_RATE_CENTS,
    TIER2_RATE_CENTS,
    DEDUCTIBLE_CENTS,
    INSURANCE_TIER1_CAP_CENTS,
    INSURANCE_TIER1_RATE_IN_SCOPE,
    INSURANCE_TIER2_RATE_IN_SCOPE,
    INSURANCE_TIER1_RATE_OUT_OF_SCOPE,
    INSURANCE_TIER2_RATE_OUT_OF_SCOPE,
    ANNUAL_CAP_CENTS,
    INSURANCE_IN_SCOPE_DISEASES,
)


def triage_severity_score(questionnaire_responses, chronic_condition_codes):
    """Returns (chief, vital, risk, total, band)."""
    chief = 0
    for r in questionnaire_responses or []:
        try:
            chief += int(r.get("severity_weight", 0))
        except (TypeError, ValueError):
            pass
    chief *= CHIEF_COMPLAINT_FACTOR

    vital = 0
    for r in questionnaire_responses or []:
        qc = r.get("question_code", "")
        av = r.get("answer_value")
        if isinstance(qc, str) and qc.startswith(VITAL_PREFIX) and av == "ABNORMAL":
            vital += 1
    vital *= VITAL_ANOMALY_FACTOR

    risk = 0
    for code in chronic_condition_codes or []:
        if code in RISK_TABLE:
            risk += RISK_TABLE[code]
    risk *= RISK_FACTOR

    total = chief + vital + risk
    if total < 30:
        band = "LOW"
    elif total < 60:
        band = "MID"
    elif total < 90:
        band = "HIGH"
    else:
        band = "EMERGENCY"
    return chief, vital, risk, total, band


def _round_half_up_2dp(value: Decimal) -> Decimal:
    """Round Decimal to two decimal places using ROUND_HALF_UP."""
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _round_half_up_int(value: Decimal) -> int:
    """Round Decimal to integer using ROUND_HALF_UP."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def compute_duration_minutes(started_at_dt, ended_at_dt) -> int:
    """Elapsed minutes, ceil to next whole minute.

    Note: server-minted timestamps add small per-read monotonic nudges (microseconds)
    so successive reads are strictly increasing. When computing billable minutes,
    snap any fractional drift smaller than 1 second to zero so a 600-second
    advance_clock yields exactly 10 minutes — not 11 — even after small nudges.
    """
    total_seconds = (ended_at_dt - started_at_dt).total_seconds()
    if total_seconds <= 0:
        return 0
    # Tolerance: drop sub-second drift accumulated by monotonic-nudge reads.
    # Anything within 1ms of a clean boundary is treated as the boundary.
    seconds_int = int(total_seconds)
    fractional = total_seconds - seconds_int
    if fractional < 1e-3:
        # Treat as exact integer seconds
        effective_seconds = seconds_int
    else:
        effective_seconds = total_seconds
    import math
    return int(math.ceil(effective_seconds / 60.0))


def consultation_fee(base_fee_yuan, duration_minutes: int) -> float:
    """
    Tiered: first TIER1_CAP_MIN minutes at TIER1_RATE_CENTS, beyond that TIER2_RATE_CENTS.
    Rounding happens ONCE on the final sum (round_half_up to 2dp).
    Returns a float (2dp).
    """
    # Convert base_fee to integer cents (snapshotted yuan -> cents, exact via Decimal)
    base_cents = int(_round_half_up_int(Decimal(str(base_fee_yuan)) * Decimal("100")))
    tier1 = min(duration_minutes, TIER1_CAP_MIN)
    tier2 = max(0, duration_minutes - TIER1_CAP_MIN)
    raw_cents = base_cents + tier1 * TIER1_RATE_CENTS + tier2 * TIER2_RATE_CENTS
    # divide by 100 and round half-up to two decimals
    yuan = _round_half_up_2dp(Decimal(raw_cents) / Decimal(100))
    return float(yuan)


def insurance_reimbursement(
    claim_amount_cents: int,
    deductible_cents: int,
    disease_codes,
    has_prescription: bool,
    ytd_reimbursed_cents: int,
) -> int:
    """
    Tiered reimbursement; rounds half-up PER TIER, then sums (combinatorial mode (b)).
    Capped at ANNUAL_CAP_CENTS minus YTD reimbursed for this patient.
    """
    eligible = max(0, claim_amount_cents - deductible_cents)
    tier1_amt = min(eligible, INSURANCE_TIER1_CAP_CENTS)
    tier2_amt = max(0, eligible - INSURANCE_TIER1_CAP_CENTS)

    # Determine tier rates: in-scope if no prescription OR disease_codes intersects scope.
    in_scope = True
    if has_prescription and disease_codes is not None:
        codes_set = set(disease_codes or [])
        if codes_set and not (codes_set & INSURANCE_IN_SCOPE_DISEASES):
            in_scope = False
    if in_scope:
        rate1 = INSURANCE_TIER1_RATE_IN_SCOPE
        rate2 = INSURANCE_TIER2_RATE_IN_SCOPE
    else:
        rate1 = INSURANCE_TIER1_RATE_OUT_OF_SCOPE
        rate2 = INSURANCE_TIER2_RATE_OUT_OF_SCOPE

    t1 = _round_half_up_int(Decimal(tier1_amt) * Decimal(str(rate1)))
    t2 = _round_half_up_int(Decimal(tier2_amt) * Decimal(str(rate2)))
    reimbursed = t1 + t2
    # Annual cap headroom
    headroom = max(0, ANNUAL_CAP_CENTS - ytd_reimbursed_cents)
    return min(reimbursed, headroom)
