"""Deterministic calculations (PRD §3, scaffold §1.3).

All money is integer cents; the single rounding point is the renewal discount,
which uses round-half-up with the discount applied before rounding.
Risk scoring is integer points clamped to [0,100].
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

# Calculation constants (scaffold §1.3)
RENEWAL_DISCOUNT_RATE = Decimal("0.20")
PROCESSING_FEE_CENTS = 1175
W_CRIMINAL = 15
W_WATCHLIST = 60
W_REVOCATION = 25


def compute_fee_due(base_fee_cents: int, is_renewal: bool) -> int:
    """compute_fee_due (PRD §3.2).

    New enrollment pays full base. Renewal pays base * 0.80, discount applied to
    base BEFORE rounding, rounded to nearest whole cent half-up. No per-component
    rounding.
    """
    if not is_renewal:
        return int(base_fee_cents)
    discounted = Decimal(base_fee_cents) * (Decimal(1) - RENEWAL_DISCOUNT_RATE)
    return int(discounted.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def compute_refund_due(fee_paid_cents: int, status: str) -> int:
    """compute_refund_due (PRD §3.8).

    DRAFT/SUBMITTED -> full refund. VETTING/INTERVIEW_SCHEDULED -> paid minus
    1175 processing fee, floored at 0. DENIED/APPEAL_PENDING -> 0. Never exceeds
    what was paid.
    """
    paid = int(fee_paid_cents)
    if status in ("DRAFT", "SUBMITTED"):
        refund = paid
    elif status in ("VETTING", "INTERVIEW_SCHEDULED"):
        refund = max(0, paid - PROCESSING_FEE_CENTS)
    else:  # DENIED, APPEAL_PENDING
        refund = 0
    return max(0, min(refund, paid))


def compute_risk_score(criminal_hits: int, watchlist_hits: int, prior_revocations: int) -> int:
    """compute_risk_score (PRD §3.3).

    raw = criminal*15 + watchlist*60 + revocations*25, then clamp into [0,100]
    and store. The redress offset is applied later, AFTER the clamp.
    """
    raw = (criminal_hits * W_CRIMINAL
           + watchlist_hits * W_WATCHLIST
           + prior_revocations * W_REVOCATION)
    return min(100, max(0, raw))


def effective_score(risk_score: int, redress_offset_applied: int) -> int:
    """Effective score driving adjudication: (risk_score - offset), floored at 0.

    Pinned order (PRD §3.3): clamp risk_score first (done at storage), THEN
    subtract the offset and re-floor at 0.
    """
    return max(0, risk_score - redress_offset_applied)


def compute_redress_offset(match_strength_score: int, redress_min_score: int,
                           watchlist_hits: int):
    """compute_redress_offset (PRD §3.7).

    match_strength_score <= redress_min_score -> CLEARED, offset = 60*watchlist_hits.
    Boundary is inclusive (<=). Otherwise -> CONFIRMED, offset = 0.
    Returns (resolution, risk_offset).
    """
    if match_strength_score <= redress_min_score:
        return "CLEARED", W_WATCHLIST * watchlist_hits
    return "CONFIRMED", 0


def compute_ktn_expiry(issued_at: datetime, validity_years: int) -> datetime:
    """compute_ktn_expiry (PRD §3.6).

    issued_at advanced by validity_years calendar years (same month/day); a
    Feb-29 issuance maps to Feb-28 in a non-leap target year.
    """
    target_year = issued_at.year + validity_years
    month = issued_at.month
    day = issued_at.day
    if month == 2 and day == 29 and not _is_leap(target_year):
        day = 28
    return issued_at.replace(year=target_year, month=month, day=day)


def _is_leap(year: int) -> bool:
    return (year % 4 == 0 and year % 100 != 0) or (year % 400 == 0)


def dominant_hit_category(criminal_hits: int, watchlist_hits: int, prior_revocations: int) -> str:
    """Derive adverse_reason from the dominant weighted hit category (PRD §3.4)."""
    contributions = {
        "WATCHLIST": watchlist_hits * W_WATCHLIST,
        "REVOCATION": prior_revocations * W_REVOCATION,
        "CRIMINAL": criminal_hits * W_CRIMINAL,
    }
    # Highest weighted contribution wins; tie-break by the inherent severity
    # ordering watchlist > revocation > criminal (W_WATCHLIST is largest).
    order = ["WATCHLIST", "REVOCATION", "CRIMINAL"]
    best = max(order, key=lambda k: (contributions[k], -order.index(k)))
    return best
