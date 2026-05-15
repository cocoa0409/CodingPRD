"""Domain calculations (SCAFFOLD §1.3, PRD §3).

All money is integer cents. All rates are integer basis points.
Rounding direction is round-half-up at the boundary explicitly pinned by each
calculation. Variant A vs Variant B for total-due differ in rounding cadence
and are NOT interchangeable.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable

from .constants import (
    APR_CEILING_BPS,
    APR_FLOOR_BPS,
    CAPITAL_GOODS_TOLERANCE_BPS,
    CORE_RISK_ADJ_BPS,
    MODE_BASE_BPS,
    PENALTY_BPS_BY_BUCKET,
    PLATFORM_FEE_BPS,
    REVERSE_FACTOR_CORE_KYC_MAP,
    SUPPLIER_RISK_ADJ_BPS,
    W_AML,
    W_KYC,
    W_TIER,
)


def _round_half_up_int(value) -> int:
    d = Decimal(str(value))
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _round_half_up_2(value) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# ----------------------------------------------------------------------------
# 3.1 financing_apr_pricing — tiered APR (basis points)
# ----------------------------------------------------------------------------
def compute_approved_apr_bps(
    mode: str,
    core_risk_rating: str,
    supplier_app_risk_rating: str,
    supplier_tier: int,
) -> int:
    base = MODE_BASE_BPS[mode]
    core_adj = CORE_RISK_ADJ_BPS.get(core_risk_rating, 0)
    supplier_adj = SUPPLIER_RISK_ADJ_BPS.get(supplier_app_risk_rating, 0)
    tier_adj = (int(supplier_tier) - 1) * 50
    raw = base + core_adj + supplier_adj + tier_adj
    return max(APR_FLOOR_BPS, min(APR_CEILING_BPS, raw))


def compute_effective_apr_bps(approved_apr_bps: int, term_days: int) -> int:
    """For DYNAMIC_DISCOUNTING — pro-rates the annualised APR by term."""
    d = Decimal(approved_apr_bps) * Decimal(term_days) / Decimal(365)
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ----------------------------------------------------------------------------
# 3.2 financing_total_due — Variant A (forward-looking, one rounding over term)
# ----------------------------------------------------------------------------
def variant_a_total_due(
    principal_cents: int,
    approved_apr_bps: int,
    term_days: int,
) -> tuple[int, int, int]:
    """Returns (interest_cents, fees_cents, total_due_cents)."""
    interest = (Decimal(principal_cents) * Decimal(approved_apr_bps) * Decimal(term_days)) / (
        Decimal(10000) * Decimal(365)
    )
    interest_cents = _round_half_up_int(interest)
    fees = (Decimal(principal_cents) * Decimal(PLATFORM_FEE_BPS)) / Decimal(10000)
    fees_cents = _round_half_up_int(fees)
    return interest_cents, fees_cents, principal_cents + interest_cents + fees_cents


def variant_a_dynamic_discount_cents(
    principal_cents: int, effective_apr_bps: int
) -> int:
    """DYNAMIC_DISCOUNTING: a one-time prepaid discount withheld from supplier.
    Computed as principal * effective_apr_bps / 10000, rounded half-up to cents.
    """
    d = (Decimal(principal_cents) * Decimal(effective_apr_bps)) / Decimal(10000)
    return _round_half_up_int(d)


# ----------------------------------------------------------------------------
# 3.3 financing_total_due — Variant B (chronological day-by-day)
# Used for early-settle and overdue-penalty.
# Order pinned: round each daily slice first, then sum, then add fees and
# subtract any prepaid principal.
# ----------------------------------------------------------------------------
def variant_b_total_due(
    principal_cents: int,
    approved_apr_bps: int,
    released_at: datetime,
    settle_date: datetime,
    fees_cents: int,
    prepayments: Iterable[tuple[datetime, int]] = (),
) -> int:
    """Walks the calendar from released_at (exclusive of day 0? PRD says day-by-day
    from released_at forward) and accrues daily interest on the outstanding
    principal at the start of each day.

    `prepayments` is an iterable of (when_dt, prepay_principal_cents). A
    prepayment recorded on a day reduces the outstanding before subsequent
    daily slices accrue.
    Returns total_due_cents = principal - sum_prepaid + summed_interest + fees.
    """
    if settle_date <= released_at:
        # No interest accrues
        prepaid = sum(p for _, p in prepayments) if prepayments else 0
        return max(0, principal_cents - prepaid + fees_cents)

    # Number of whole days the interest accrues over.
    # We use floor((settle - release).total_seconds()/86400) — i.e. integer days.
    total_seconds = (settle_date - released_at).total_seconds()
    days = int(total_seconds // 86400)
    if days <= 0:
        prepaid = sum(p for _, p in prepayments) if prepayments else 0
        return max(0, principal_cents - prepaid + fees_cents)

    # Bucket prepayments by their absolute day index from released_at.
    prepay_by_day: dict[int, int] = {}
    for when, amount in prepayments:
        if when <= released_at:
            day_idx = 0
        else:
            day_idx = int((when - released_at).total_seconds() // 86400)
        prepay_by_day[day_idx] = prepay_by_day.get(day_idx, 0) + int(amount)

    outstanding = principal_cents
    interest_sum = 0
    for d_idx in range(days):
        # Apply any prepayment that landed on this day BEFORE charging interest
        if d_idx in prepay_by_day:
            outstanding -= prepay_by_day[d_idx]
            if outstanding < 0:
                outstanding = 0
        daily = (Decimal(outstanding) * Decimal(approved_apr_bps)) / (
            Decimal(10000) * Decimal(365)
        )
        interest_sum += _round_half_up_int(daily)
    # Any prepayment that lands ON the settle day itself is also folded in
    if days in prepay_by_day:
        outstanding -= prepay_by_day[days]
        if outstanding < 0:
            outstanding = 0

    prepaid_total = sum(prepay_by_day.values())
    return max(0, principal_cents - prepaid_total + interest_sum + fees_cents)


# ----------------------------------------------------------------------------
# 3.4 early_settle_rebate (PRD §3.7)
# rebate = max(0, forward_total - chronological_total)
# Pin: round daily, then sum, then take the difference against the forward total.
# ----------------------------------------------------------------------------
def early_settle_rebate_cents(
    forward_total_cents: int,
    chrono_total_cents: int,
) -> int:
    return max(0, int(forward_total_cents) - int(chrono_total_cents))


# ----------------------------------------------------------------------------
# 3.5 overdue_penalty_aging — bucket assignment + daily penalty
# ----------------------------------------------------------------------------
def days_past_due(scheduled_repayment_date: datetime, now: datetime) -> int:
    """Floor of days between scheduled and now. dpd<=0 means not yet overdue."""
    if now <= scheduled_repayment_date:
        return 0
    seconds = (now - scheduled_repayment_date).total_seconds()
    return int(seconds // 86400)


def aging_bucket_for_dpd(dpd: int):
    if dpd <= 0:
        return None
    if dpd <= 30:
        return "DPD_1_30"
    if dpd <= 60:
        return "DPD_31_60"
    if dpd <= 90:
        return "DPD_61_90"
    return "DPD_OVER_90"


def overdue_total_penalty_cents(
    outstanding_cents: int,
    scheduled_repayment_date: datetime,
    now: datetime,
) -> int:
    """Sum of daily penalty across the dpd days. Per-day rounding, then sum.

    The PRD pins per-day rounding before summation; rate per day is determined
    by the bucket that contains that calendar day (i.e. the bucket index for
    day k = aging_bucket_for_dpd(k+1) so the very first overdue day uses DPD_1_30).
    """
    dpd = days_past_due(scheduled_repayment_date, now)
    if dpd <= 0 or outstanding_cents <= 0:
        return 0
    total = 0
    for day in range(1, dpd + 1):
        bucket = aging_bucket_for_dpd(day)
        if bucket is None:
            continue
        rate_bps = PENALTY_BPS_BY_BUCKET[bucket]
        daily = (Decimal(outstanding_cents) * Decimal(rate_bps)) / (Decimal(10000) * Decimal(365))
        total += _round_half_up_int(daily)
    return total


# ----------------------------------------------------------------------------
# 3.6 supplier_risk_rating_composite — weighted scoring, one rounding at end
# ----------------------------------------------------------------------------
def composite_risk_score(
    mode: str,
    kyc_status: str,
    aml_risk_score: float,
    tier_to_core: int,
    core_risk_rating: str | None = None,
) -> Decimal:
    if mode == "REVERSE_FACTORING":
        kyc_factor = Decimal(str(REVERSE_FACTOR_CORE_KYC_MAP.get(core_risk_rating or "BBB", 0.7)))
    else:
        kyc_factor = Decimal("1.0") if kyc_status == "PASSED" else Decimal("0.0")
    aml_factor = Decimal("1.0") - Decimal(str(aml_risk_score))
    if aml_factor < 0:
        aml_factor = Decimal("0")
    tier_factor = Decimal("1.0") - Decimal(tier_to_core - 1) * Decimal("0.20")
    if tier_factor < 0:
        tier_factor = Decimal("0")
    raw = (
        Decimal(str(W_KYC)) * kyc_factor
        + Decimal(str(W_AML)) * aml_factor
        + Decimal(str(W_TIER)) * tier_factor
    )
    return _round_half_up_2(raw)


def composite_to_rating(score: Decimal) -> str:
    if score >= Decimal("0.80"):
        return "LOW"
    if score >= Decimal("0.60"):
        return "MEDIUM"
    if score >= Decimal("0.40"):
        return "HIGH"
    return "REJECT"


# ----------------------------------------------------------------------------
# 3.7 capital_goods_consistency — deviation in basis points, rounded half-up
# ----------------------------------------------------------------------------
def capital_goods_match(capital_cents: int, goods_cents: int) -> bool:
    """Single waybill (or single customs declaration) check."""
    if goods_cents <= 0:
        return False
    deviation = (Decimal(abs(capital_cents - goods_cents)) * Decimal(10000)) / Decimal(goods_cents)
    dev_bps = _round_half_up_int(deviation)
    return dev_bps <= CAPITAL_GOODS_TOLERANCE_BPS
