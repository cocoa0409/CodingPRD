"""Domain calculations: franchise tax, late fees, BOI penalty, exposure score, total due."""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from math import ceil, floor
from typing import Any


# ---- Constants from the scaffold ---------------------------------------------------
LLC_LP_FLAT_TAX_CENTS = 30000
CORP_TIER1_MAX_SHARES = 5000
CORP_TIER1_TAX_CENTS = 17500
CORP_TIER2_MAX_SHARES = 10000
CORP_TIER2_TAX_CENTS = 25000
CORP_TIER3_BLOCK_SHARES = 10000
CORP_TIER3_BLOCK_TAX_CENTS = 8500
ASSUMED_PAR_MILLION_CENTS = 100_000_000
ASSUMED_PAR_PER_MILLION_TAX_CENTS = 40000

LATE_FEE_FLAT_CENTS = 20000
LATE_FEE_MONTH_CAP = 18
# 0.015 as exact decimal — never float
MONTHLY_INTEREST_RATE = Decimal("0.015")

DAILY_PENALTY_CENTS = 59100
PENALTY_CAP_CENTS = 1_000_000

RISK_FOREIGN_PASSPORT = Decimal(3)
RISK_STATE_ID = Decimal(2)
RISK_DEFAULT = Decimal(1)


# ---- Franchise tax base calculations -----------------------------------------------

def authorized_shares_base_tax(authorized_shares: int) -> int:
    """CORP variant A: tiered ladder over authorized_shares."""
    if authorized_shares <= CORP_TIER1_MAX_SHARES:
        return CORP_TIER1_TAX_CENTS
    if authorized_shares <= CORP_TIER2_MAX_SHARES:
        return CORP_TIER2_TAX_CENTS
    extra = authorized_shares - CORP_TIER2_MAX_SHARES
    blocks = ceil(extra / CORP_TIER3_BLOCK_SHARES)
    return CORP_TIER2_TAX_CENTS + blocks * CORP_TIER3_BLOCK_TAX_CENTS


def assumed_par_value_base_tax(total_gross_assets_cents: int, total_issued_shares: int, authorized_shares: int) -> int:
    """CORP variant B: assumed-par-value capital rounded up to the next million."""
    if total_issued_shares <= 0:
        raise ValueError("total_issued_shares must be > 0 for ASSUMED_PAR_VALUE")
    # Exact rational chain: avoid float.
    # apvc_cents = (total_gross_assets_cents * authorized_shares) / total_issued_shares
    numerator = Decimal(total_gross_assets_cents) * Decimal(authorized_shares)
    denominator = Decimal(total_issued_shares)
    apvc = numerator / denominator  # exact, no rounding yet
    # ceil to next million-cent block (100_000_000 cents = $1,000,000)
    millions_quot = apvc / Decimal(ASSUMED_PAR_MILLION_CENTS)
    # Decimal ceil — use to_integral_value with ROUND_CEILING via a clean conversion
    millions = int(_decimal_ceil(millions_quot))
    return millions * ASSUMED_PAR_PER_MILLION_TAX_CENTS


def _decimal_ceil(x: Decimal) -> Decimal:
    # Decimal -> ceil-integer
    if x == x.to_integral_value():
        return x.to_integral_value()
    return x.to_integral_value(rounding="ROUND_CEILING") if False else _ceil_via_int(x)


def _ceil_via_int(x: Decimal) -> Decimal:
    # Fallback: integer + 1 if there is any positive fraction.
    sign, digits, exponent = x.as_tuple()
    # If x is exactly integral, fast path:
    if x == int(x):
        return Decimal(int(x))
    int_part = int(x)  # truncates toward zero
    if x > 0:
        return Decimal(int_part + 1)
    return Decimal(int_part)


# ---- Late fee --------------------------------------------------------------------

def months_late(now: datetime, due_date: datetime) -> int:
    """Ceil((now - due_date) / 30 days), capped at LATE_FEE_MONTH_CAP. Zero if not past due."""
    if now <= due_date:
        return 0
    delta_seconds = (now - due_date).total_seconds()
    days = delta_seconds / 86400.0
    months = ceil(days / 30.0)
    if months < 0:
        months = 0
    return min(months, LATE_FEE_MONTH_CAP)


def compute_late_fee_cents(status: str, now: datetime, due_date: datetime, base_tax_cents: int) -> int:
    """Late fee formula. ASSESSED (not yet past due) and PAID always yield 0."""
    if status == "PAID":
        return 0
    if status == "ASSESSED" and now <= due_date:
        return 0
    m = months_late(now, due_date)
    if m <= 0:
        return 0
    # Per-line rounding: round_half_up(base_tax_cents * 0.015) FIRST
    monthly = (Decimal(base_tax_cents) * MONTHLY_INTEREST_RATE).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(LATE_FEE_FLAT_CENTS + int(monthly) * m)


# ---- Total due (with credit application) -----------------------------------------

def compute_total_due(assessment: dict[str, Any], entity_credit_balance: int, now: datetime) -> tuple[int, int, int]:
    """Apply the pinned five-step evaluation order.

    Returns (late_fee_cents, total_due_cents, credit_applied_cents).
    """
    status = assessment.get("status", "ASSESSED")
    if status == "PAID":
        # Frozen at payment time — use stored values.
        return (
            int(assessment.get("late_fee_cents", 0)),
            int(assessment.get("total_due_cents", 0)),
            int(assessment.get("credit_applied_cents", 0)),
        )
    base = int(assessment["base_tax_cents"])
    late = compute_late_fee_cents(status, now, assessment["due_date"], base)
    pre_credit_due = base + late
    credit_applied = min(int(entity_credit_balance), pre_credit_due)
    total_due = pre_credit_due - credit_applied
    return late, total_due, credit_applied


# ---- BOI penalty -----------------------------------------------------------------

def compute_boi_penalty(stale_at: datetime, now: datetime) -> tuple[int, int]:
    """Return (effective_days, penalty_cents) using cap-first semantics."""
    raw_days = floor((now - stale_at).total_seconds() / 86400.0)
    if raw_days < 0:
        raw_days = 0
    cap_days = floor(PENALTY_CAP_CENTS / DAILY_PENALTY_CENTS)  # 16
    effective_days = min(raw_days, cap_days)
    return effective_days, effective_days * DAILY_PENALTY_CENTS


# ---- Exposure score --------------------------------------------------------------

def owner_risk_weight(doc_type: str) -> Decimal:
    if doc_type == "FOREIGN_PASSPORT":
        return RISK_FOREIGN_PASSPORT
    if doc_type == "STATE_ID":
        return RISK_STATE_ID
    return RISK_DEFAULT


def exposure_score(rows: list[dict[str, Any]], owner_lookup: dict[str, dict[str, Any]]) -> float:
    """Sum of (bps/10000) * risk_weight over the supplied rows, rounded half-up to 2dp."""
    total = Decimal(0)
    for row in rows:
        owner = owner_lookup.get(row.get("beneficial_owner_id"))
        if owner is None:
            continue
        weight = owner_risk_weight(owner.get("identifying_document_type", ""))
        share = Decimal(row.get("ownership_percent_basis_points", 0)) / Decimal(10000)
        total += share * weight
    rounded = total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(rounded)
