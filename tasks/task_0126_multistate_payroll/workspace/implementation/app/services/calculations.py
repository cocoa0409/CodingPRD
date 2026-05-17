"""Tax calculation engine — federal/state/local withholding, FICA, Medicare, garnishment waterfall."""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from ..helpers import round_half_up
from .constants import (
    ADDITIONAL_MEDICARE_RATE_BPS,
    ADDITIONAL_MEDICARE_THRESHOLD_CENTS,
    CCPA_BASE_PCT,
    CCPA_CHILD_SUPPORT_PCT,
    FED_BRACKETS,
    LOCAL_FLAT_RATE_BPS,
    MEDICARE_BASE_RATE_BPS,
    PAY_PERIODS_PER_YEAR,
    SS_RATE_BPS,
    SS_WAGE_BASE_CENTS,
    STANDARD_DEDUCTION_CENTS,
    STATE_ALLOWANCE_VALUE_CENTS,
    STATE_BRACKETS,
    STATE_STANDARD_DEDUCTION_CENTS,
    SUPPLEMENTAL_FED_RATE_BPS,
)


# ---------------------------------------------------------------------------
# Gross wages
# ---------------------------------------------------------------------------

def compute_gross_cents(
    regular_hours: float,
    overtime_hours: float,
    double_hours: float,
    retro_adjustment_cents: int,
    hourly_rate_cents: int,
) -> int:
    """gross = reg*rate + 1.5*ot*rate + 2*dbl*rate + retro, rounded half up to whole cents.

    Use Decimal arithmetic for the hours-times-rate products so that decimal
    hours like 7.25 produce exact results.
    """
    rate = Decimal(hourly_rate_cents)
    reg = Decimal(str(regular_hours)) * rate
    ot = Decimal(str(overtime_hours)) * Decimal("1.5") * rate
    dbl = Decimal(str(double_hours)) * Decimal(2) * rate
    total = reg + ot + dbl + Decimal(retro_adjustment_cents)
    return round_half_up(total)


def compute_non_retro_gross_cents(
    regular_hours: float,
    overtime_hours: float,
    double_hours: float,
    hourly_rate_cents: int,
) -> int:
    """Gross excluding retro — for supplemental-rate split."""
    rate = Decimal(hourly_rate_cents)
    reg = Decimal(str(regular_hours)) * rate
    ot = Decimal(str(overtime_hours)) * Decimal("1.5") * rate
    dbl = Decimal(str(double_hours)) * Decimal(2) * rate
    return round_half_up(reg + ot + dbl)


# ---------------------------------------------------------------------------
# Piecewise bracket evaluation
# ---------------------------------------------------------------------------

def piecewise_tier_apply(taxable_cents: int, brackets: list[dict]) -> int:
    """Apply a piecewise marginal bracket table. Returns the tax in cents (not yet rounded).

    For each bracket: tax += (min(taxable, hi) - lo) * rate_bps / 10000 when taxable > lo.
    """
    if taxable_cents <= 0:
        return 0
    total = Decimal(0)
    for b in brackets:
        lo = b["lo"]
        hi = b["hi"]
        rate_bps = b["rate_bps"]
        if taxable_cents <= lo:
            break
        upper_bound = taxable_cents if hi is None else min(taxable_cents, hi)
        slice_amount = upper_bound - lo
        if slice_amount <= 0:
            continue
        total += Decimal(slice_amount) * Decimal(rate_bps) / Decimal(10000)
        if hi is None or taxable_cents <= hi:
            break
    return round_half_up(total)


# ---------------------------------------------------------------------------
# Federal withholding — annualized
# ---------------------------------------------------------------------------

def federal_withholding_annualized(
    gross_for_annualization_cents: int,
    w4: dict[str, Any],
) -> int:
    """Per-paycheck federal withholding using IRS annualized projection."""
    filing_status = w4["filing_status"]
    annualized = gross_for_annualization_cents * PAY_PERIODS_PER_YEAR
    annualized += w4.get("other_income_cents", 0)
    std_deduction = STANDARD_DEDUCTION_CENTS[filing_status]
    taxable_annual = max(0, annualized - std_deduction)
    annual_tax = piecewise_tier_apply(taxable_annual, FED_BRACKETS[filing_status])
    annual_tax = max(0, annual_tax - w4.get("dependents_amount_cents", 0))
    # per-paycheck portion + additional withholding
    per_paycheck = Decimal(annual_tax) / Decimal(PAY_PERIODS_PER_YEAR)
    per_paycheck += Decimal(w4.get("additional_withholding_cents", 0))
    return round_half_up(per_paycheck)


def federal_withholding_with_retro(
    non_retro_gross_cents: int,
    retro_adjustment_cents: int,
    w4: dict[str, Any],
) -> int:
    """Supplemental flat-rate split for retro adjustments.

    Non-retro portion runs through annualized; retro portion is taxed at 22% flat.
    Each piece is rounded half-up independently then summed.
    """
    standard_part = federal_withholding_annualized(non_retro_gross_cents, w4)
    # Retro at supplemental flat 22% — applies to both positive and negative retro.
    # For a negative retro (clawback), withholding becomes negative which reduces total.
    retro_tax = Decimal(retro_adjustment_cents) * Decimal(SUPPLEMENTAL_FED_RATE_BPS) / Decimal(10000)
    retro_part = round_half_up(retro_tax)
    return standard_part + retro_part


# ---------------------------------------------------------------------------
# State withholding
# ---------------------------------------------------------------------------

def state_brackets_for(state: str, filing_status: str) -> list[dict] | None:
    table = STATE_BRACKETS.get(state)
    if table is None:
        return None
    if "ANY" in table:
        return table["ANY"]
    return table.get(filing_status)


def state_withholding_annualized(
    gross_for_annualization_cents: int,
    state: str,
    w4: dict[str, Any],
) -> int:
    """State income tax mirroring the federal annualized algorithm."""
    if state == "TX":
        return 0
    brackets = state_brackets_for(state, w4["filing_status"])
    if not brackets:
        return 0
    annualized = gross_for_annualization_cents * PAY_PERIODS_PER_YEAR
    allowances = w4.get("state_allowances", 0) or 0
    annualized -= allowances * STATE_ALLOWANCE_VALUE_CENTS
    taxable_annual = max(0, annualized - STATE_STANDARD_DEDUCTION_CENTS)
    annual_tax = piecewise_tier_apply(taxable_annual, brackets)
    per_paycheck = Decimal(annual_tax) / Decimal(PAY_PERIODS_PER_YEAR)
    return round_half_up(per_paycheck)


def state_withholding_with_retro(
    non_retro_gross_cents: int,
    retro_adjustment_cents: int,
    state: str,
    w4: dict[str, Any],
) -> int:
    """State supplemental: non-retro annualized, retro at the state flat supplemental rate.

    The PRD says state retro follows the state-specific supplemental rate where one is
    configured. We use the state's effective rate from its first bracket as the
    supplemental rate (i.e., flat-state rates apply directly; bracketed states use the
    top bracket as supplemental — keep it simple and use the average top rate).
    For this implementation we re-use the annualized method on the non-retro portion
    and compute retro using the same per-state piecewise table evaluated at the retro
    amount (treating retro as the only marginal slice). This matches the PRD's
    spirit: a state-specific supplemental rate based on its bracket regime.
    However, to keep IL/PA/TX flat semantics, we use the state's flat or top rate.
    """
    standard_part = state_withholding_annualized(non_retro_gross_cents, state, w4)
    if state == "TX":
        return standard_part
    brackets = state_brackets_for(state, w4["filing_status"])
    if not brackets:
        return standard_part
    # Use the topmost-bracket rate as supplemental rate (this matches most state
    # supplemental wage regimes — e.g. CA top rate, NY top rate). For flat-rate
    # states this is the only bracket.
    top_rate_bps = brackets[-1]["rate_bps"]
    retro_tax = Decimal(retro_adjustment_cents) * Decimal(top_rate_bps) / Decimal(10000)
    return standard_part + round_half_up(retro_tax)


# ---------------------------------------------------------------------------
# Local withholding
# ---------------------------------------------------------------------------

def local_withholding(gross_cents: int, locality: str) -> int:
    rate_bps = LOCAL_FLAT_RATE_BPS.get(locality, 0)
    if rate_bps == 0:
        return 0
    return round_half_up(Decimal(gross_cents) * Decimal(rate_bps) / Decimal(10000))


# ---------------------------------------------------------------------------
# FICA — Social Security
# ---------------------------------------------------------------------------

def social_security(gross_cents: int, ytd_ss_before_cents: int) -> tuple[int, int]:
    """Returns (ss_withholding_cents, taxable_ss_wages_cents).

    The second return is the portion that contributes to YTD Social Security wages
    (the amount of this paycheck's gross that was subject to SS).
    """
    remaining_room = max(0, SS_WAGE_BASE_CENTS - ytd_ss_before_cents)
    taxable_ss = min(gross_cents, remaining_room)
    if taxable_ss <= 0:
        return 0, 0
    ss_withholding = round_half_up(Decimal(taxable_ss) * Decimal(SS_RATE_BPS) / Decimal(10000))
    return ss_withholding, taxable_ss


# ---------------------------------------------------------------------------
# Medicare
# ---------------------------------------------------------------------------

def medicare_base(gross_cents: int) -> int:
    return round_half_up(Decimal(gross_cents) * Decimal(MEDICARE_BASE_RATE_BPS) / Decimal(10000))


def medicare_additional(gross_cents: int, ytd_med_before_cents: int) -> int:
    """Additional Medicare 0.9% on YTD Medicare wages above $200,000."""
    ytd_med_after = ytd_med_before_cents + gross_cents
    if ytd_med_after <= ADDITIONAL_MEDICARE_THRESHOLD_CENTS:
        return 0
    if ytd_med_before_cents >= ADDITIONAL_MEDICARE_THRESHOLD_CENTS:
        excess = gross_cents
    else:
        excess = ytd_med_after - ADDITIONAL_MEDICARE_THRESHOLD_CENTS
    return round_half_up(Decimal(excess) * Decimal(ADDITIONAL_MEDICARE_RATE_BPS) / Decimal(10000))


# ---------------------------------------------------------------------------
# Garnishment waterfall
# ---------------------------------------------------------------------------

def garnishment_waterfall(
    disposable_cents: int,
    active_orders: list[dict[str, Any]],
) -> tuple[int, dict[str, int]]:
    """Compute per-order allocations and the total garnishment for this paycheck.

    active_orders: list of dicts (orders), pre-filtered to status=ACTIVE and
    effective_pay_date <= pay_date, AND already sorted by (priority_rank,
    created_at, id) ascending.

    Returns (garnishment_total_cents, per_order_allocations_by_order_id).
    """
    if not active_orders or disposable_cents <= 0:
        return 0, {}

    # CCPA cap: 50% if any active CHILD_SUPPORT, else 25%
    has_child_support = any(o["order_type"] == "CHILD_SUPPORT" for o in active_orders)
    cap_pct = CCPA_CHILD_SUPPORT_PCT if has_child_support else CCPA_BASE_PCT
    ccpa_cap = round_half_up(Decimal(disposable_cents) * Decimal(cap_pct) / Decimal(100))

    remaining_pool = ccpa_cap
    allocations: dict[str, int] = {}

    for order in active_orders:
        if remaining_pool <= 0:
            break
        per_order_cap = round_half_up(
            Decimal(disposable_cents) * Decimal(order["cap_pct_of_disposable"]) / Decimal(100)
        )
        remaining_owed = order["total_owed_cents"] - order["amount_collected_cents"]
        if remaining_owed <= 0:
            continue
        allocation = min(per_order_cap, remaining_owed, remaining_pool)
        if allocation <= 0:
            continue
        allocations[order["id"]] = allocation
        remaining_pool -= allocation

    total = sum(allocations.values())
    return total, allocations
