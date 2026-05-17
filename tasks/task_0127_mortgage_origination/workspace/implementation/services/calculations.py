"""Calculation engine (SCAFFOLD §1.3 / PRD §3.6, §3.7)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import db
from config import (
    APPRAISAL_VALIDITY_DAYS,
    APR_TOLERANCE_BPS,
    DEFAULT_STATE_TAX_RATE,
    DISC_NON_TERMINAL,
    DISC_SUPERSEDED,
    DISCLOSURE_KIND_LE,
    DISCLOSURE_KIND_CD,
    DTI_ESTIMATION_RATE_FACTOR,
    DTI_PRECISION_DECIMALS,
    EXTENSION_FEE_BPS,
    HOLIDAYS_2026,
    LOCK_FEE_BPS,
    LTV_PRECISION_DECIMALS,
    ORIGINATION_FEE_TIER_HIGH,
    ORIGINATION_FEE_TIER_LOW,
    ORIGINATION_FEE_TIER_MID,
    PMI_THRESHOLD,
    STATE_TAX_RATES,
    TIER_LOW_CENTS,
    TIER_MID_CENTS,
    TRID_BUSINESS_DAYS_REQUIRED,
    VER_VERIFIED,
)
from utils import (
    add_days,
    end_of_day_utc,
    round_half_up,
    round_half_up_int,
    start_of_day_utc,
    to_iso_millis,
)


# -------------------------------------------------------------------------
# DTI calculation (SCAFFOLD calc.dti_calculation, PRD §3.7)
# -------------------------------------------------------------------------
def compute_dti(application: dict, borrower: dict, variant: str) -> Decimal:
    """Compute dti_ratio per the pre-qualification or underwriting variant.

    For the underwriting variant, returns None if no VERIFIED IncomeVerification rows exist.
    """
    verified_sum = sum(
        iv["documented_annual_cents"]
        for iv in db.income_verifications.values()
        if iv["application_id"] == application["id"] and iv["status"] == VER_VERIFIED
    )

    if variant == "underwriting":
        if verified_sum <= 0:
            return None  # Caller must surface ERR_MISSING_DEPENDENCIES.
        effective_income_cents = verified_sum
    else:
        # Pre-qualification: fall back to Borrower.annual_income_cents when no verified income.
        effective_income_cents = (
            verified_sum if verified_sum > 0 else borrower["annual_income_cents"]
        )

    if effective_income_cents <= 0:
        return None

    monthly_income = Decimal(effective_income_cents) / Decimal(12)
    approx_monthly_payment = (
        Decimal(application["requested_loan_amount_cents"]) * DTI_ESTIMATION_RATE_FACTOR
    )
    dti = approx_monthly_payment / monthly_income
    return round_half_up(dti, DTI_PRECISION_DECIMALS)


# -------------------------------------------------------------------------
# LTV calculation (SCAFFOLD calc.ltv_calculation, PRD §3.7)
# -------------------------------------------------------------------------
def compute_ltv(application: dict, appraisal: dict | None) -> Decimal | None:
    """Compute ltv_ratio = principal / MIN(sale_price, appraised_value).

    Uses counter_offered_amount_cents if present, else requested_loan_amount_cents.
    Returns None when no completed appraisal is available.
    """
    if appraisal is None:
        return None
    appraised = appraisal.get("appraised_value_cents")
    if appraised is None:
        return None
    value_basis = min(application["sale_price_cents"], appraised)
    if value_basis <= 0:
        return None
    principal = application.get("counter_offered_amount_cents") or application[
        "requested_loan_amount_cents"
    ]
    ltv = Decimal(principal) / Decimal(value_basis)
    return round_half_up(ltv, LTV_PRECISION_DECIMALS)


def pmi_required_from_ltv(ltv: Decimal | None) -> bool:
    if ltv is None:
        return False
    return ltv > PMI_THRESHOLD


# -------------------------------------------------------------------------
# APR tolerance check (SCAFFOLD calc.apr_tolerance_check, PRD §3.6)
# -------------------------------------------------------------------------
def apr_tolerance_exceeded(new_cd_apr_bps: int, latest_le_apr_bps: int | None) -> bool:
    """Return True iff a CD's APR vs latest LE exceeds the strict-12-bps tolerance."""
    if latest_le_apr_bps is None:
        return False  # No prior LE — nothing to compare.
    delta = abs(int(new_cd_apr_bps) - int(latest_le_apr_bps))
    return delta > APR_TOLERANCE_BPS


def le_cd_apr_delta_exceeds(latest_cd_apr_bps: int | None, new_le_apr_bps: int) -> bool:
    """Cascading re-disclosure: when a new LE differs from latest CD by > 12 bps."""
    if latest_cd_apr_bps is None:
        return False
    delta = abs(int(new_le_apr_bps) - int(latest_cd_apr_bps))
    return delta > APR_TOLERANCE_BPS


# -------------------------------------------------------------------------
# Closing-cost / cash-to-close (SCAFFOLD calc.closing_cost_total, PRD §3.6)
# -------------------------------------------------------------------------
def _state_tax_rate(state_code: str | None) -> Decimal:
    if not state_code:
        return DEFAULT_STATE_TAX_RATE
    return STATE_TAX_RATES.get(state_code.upper(), DEFAULT_STATE_TAX_RATE)


def _origination_fee_cents(principal_cents: int) -> int:
    principal = Decimal(principal_cents)
    if principal_cents <= TIER_LOW_CENTS:
        raw = principal * ORIGINATION_FEE_TIER_LOW
    elif principal_cents <= TIER_MID_CENTS:
        raw = principal * ORIGINATION_FEE_TIER_MID
    else:
        raw = principal * ORIGINATION_FEE_TIER_HIGH
    return round_half_up_int(raw)


def compute_cash_to_close(
    total_loan_costs_cents: int,
    total_other_costs_cents: int,
    requested_loan_amount_cents: int,
    state_code: str | None,
) -> int:
    """Pinned-order closing-cost calculation per PRD §3.6.

    Step 1: per-line tax round (we model 'lines' as the single total_other_costs_cents bucket;
            this is the canonical interpretation — there is exactly one cost line whose tax we
            individually round before summing).
    Step 2: sum rounded taxes onto total_other_costs.
    Step 3: tiered origination fee (rounded to cents).
    Step 4: total = total_loan_costs + taxed_other + origination - principal, ROUND_HALF_UP.
    """
    rate = _state_tax_rate(state_code)
    # Per-line tax (single line): round individually first.
    tax_line = round_half_up_int(Decimal(total_other_costs_cents) * rate)
    taxed_other_costs_cents = tax_line + int(total_other_costs_cents)

    origination_fee = _origination_fee_cents(requested_loan_amount_cents)

    raw_total = (
        Decimal(total_loan_costs_cents)
        + Decimal(taxed_other_costs_cents)
        + Decimal(origination_fee)
        - Decimal(requested_loan_amount_cents)
    )
    return round_half_up_int(raw_total)


# -------------------------------------------------------------------------
# TRID waiting period (SCAFFOLD calc.trid_waiting_period, PRD §3.6)
# -------------------------------------------------------------------------
def _is_business_day(d: datetime) -> bool:
    if d.weekday() >= 5:  # 5=Sat, 6=Sun
        return False
    iso = d.strftime("%Y-%m-%d")
    return iso not in HOLIDAYS_2026


def compute_eligible_to_consummate_at(issued_at: datetime) -> str:
    """Advance issued_at by exactly 3 business days; anchor at 00:00:00.000 UTC."""
    cursor = issued_at
    added = 0
    while added < TRID_BUSINESS_DAYS_REQUIRED:
        cursor = cursor + timedelta(days=1)
        if _is_business_day(cursor):
            added += 1
    eligible = start_of_day_utc(cursor)
    return to_iso_millis(eligible)


# -------------------------------------------------------------------------
# Rate-lock extension fee (SCAFFOLD calc.rate_lock_extension_fee)
# -------------------------------------------------------------------------
def compute_extension_fee_cents(extra_days: int, requested_loan_amount_cents: int) -> int:
    bps = EXTENSION_FEE_BPS[int(extra_days)]
    raw = Decimal(requested_loan_amount_cents) * (Decimal(bps) / Decimal(10000))
    return round_half_up_int(raw)


def compute_lock_fee_cents(requested_loan_amount_cents: int) -> int:
    raw = Decimal(requested_loan_amount_cents) * (Decimal(LOCK_FEE_BPS) / Decimal(10000))
    return round_half_up_int(raw)


# -------------------------------------------------------------------------
# Appraisal validity window
# -------------------------------------------------------------------------
def compute_appraisal_valid_until(report_date: datetime) -> str:
    end = end_of_day_utc(add_days(report_date, APPRAISAL_VALIDITY_DAYS))
    return to_iso_millis(end)
