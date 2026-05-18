"""Calculation rules from SCAFFOLD.yaml §1.3.

This module is deliberately free of Flask/HTTP concerns.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, Iterable

from app.util import round_half_up_money


# ---------------------------------------------------------------------------
# Title insurance premium
# ---------------------------------------------------------------------------
TIER1_RATE = Decimal("5.00")
TIER2_RATE = Decimal("4.00")
TIER3_RATE = Decimal("3.00")
OWNERS_MIN_PREMIUM = Decimal("300.00")
LENDERS_MIN_PREMIUM = Decimal("200.00")
SIMULTANEOUS_DISCOUNT_FACTOR = Decimal("0.40")


def _tiered_base(insured_amount: Decimal) -> Decimal:
    thousands = (insured_amount / Decimal(1000))
    t1 = min(thousands, Decimal(100))
    t2 = min(max(thousands - Decimal(100), Decimal(0)), Decimal(400))
    t3 = max(thousands - Decimal(500), Decimal(0))
    return t1 * TIER1_RATE + t2 * TIER2_RATE + t3 * TIER3_RATE


def title_insurance_premium(
    *,
    policy_kind: str,
    insured_amount: Decimal,
    simultaneous_issue: bool,
    has_bound_owners_peer: bool,
) -> Decimal:
    """Compute the title insurance premium.

    The simultaneous-issue discount is honored only when policy_kind == LENDERS,
    simultaneous_issue is true, AND a peer OWNERS policy is already BOUND.
    """
    base = _tiered_base(insured_amount)
    if policy_kind == "OWNERS":
        return max(round_half_up_money(base), OWNERS_MIN_PREMIUM)
    # LENDERS
    if simultaneous_issue and has_bound_owners_peer:
        discounted = round_half_up_money(base * SIMULTANEOUS_DISCOUNT_FACTOR)
        return max(discounted, LENDERS_MIN_PREMIUM)
    return max(round_half_up_money(base), LENDERS_MIN_PREMIUM)


# ---------------------------------------------------------------------------
# Cash-to-close
# ---------------------------------------------------------------------------
YEAR_BASIS_DAYS = Decimal(365)


def proration_credits(
    *,
    tax_annual: Decimal,
    hoa_annual_dues: Decimal,
    seller_days_owned: int,
) -> Dict[str, Decimal]:
    """Pro-rate each line item to cents independently.

    The order pin: round per-line-item BEFORE summing.
    """
    days = Decimal(seller_days_owned)
    tax_raw = tax_annual * days / YEAR_BASIS_DAYS
    hoa_raw = hoa_annual_dues * days / YEAR_BASIS_DAYS
    return {
        "prorated_tax_credit": round_half_up_money(tax_raw),
        "prorated_hoa_credit": round_half_up_money(hoa_raw),
    }


def compute_cash_to_close(
    *,
    purchase_price: Decimal,
    loan_amount: Decimal,
    emd_credited: Decimal,
    seller_credits: Decimal,
    prorated_tax_credit: Decimal,
    prorated_hoa_credit: Decimal,
    total_loan_costs: Decimal,
) -> Decimal:
    total = (
        purchase_price
        - loan_amount
        - emd_credited
        - seller_credits
        - prorated_tax_credit
        - prorated_hoa_credit
        + total_loan_costs
    )
    # Each operand is already at 2dp so the sum is exact; we still quantize for safety.
    return total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# §1031 gain
# ---------------------------------------------------------------------------
def section_1031_gain_initial(
    *,
    relinquished_basis: Decimal,
    relinquished_sale_price: Decimal,
    cash_boot_received: Decimal,
    mortgage_relief: Decimal,
) -> Dict[str, Decimal]:
    realized_gain = round_half_up_money(relinquished_sale_price - relinquished_basis)
    boot_total = round_half_up_money(cash_boot_received + mortgage_relief)
    # Variant A — deferred path values.
    recognized = min(realized_gain, boot_total) if boot_total > 0 else min(realized_gain, boot_total)
    # If realized_gain is negative (a loss) the min picks the smaller — but the
    # closed-form definition is still recognized = min(realized, boot). Both
    # cases keep the invariant.
    deferred = realized_gain - recognized
    return {
        "realized_gain": realized_gain,
        "recognized_gain": recognized,
        "deferred_gain": deferred,
    }


# ---------------------------------------------------------------------------
# Business-day clock (3-business-day rule)
# ---------------------------------------------------------------------------
_SUNDAY = 6  # Python: Monday=0, Sunday=6


def _nth_weekday_of_month(year: int, month: int, weekday: int, n: int) -> date:
    """Return the nth occurrence of ``weekday`` in ``month`` (1-indexed)."""
    d = date(year, month, 1)
    # weekday: Monday=0..Sunday=6
    delta = (weekday - d.weekday()) % 7
    first = d + timedelta(days=delta)
    return first + timedelta(days=7 * (n - 1))


def _last_weekday_of_month(year: int, month: int, weekday: int) -> date:
    # Find the last day of the month, walk back.
    if month == 12:
        next_month = date(year + 1, 1, 1)
    else:
        next_month = date(year, month + 1, 1)
    last_day = next_month - timedelta(days=1)
    delta = (last_day.weekday() - weekday) % 7
    return last_day - timedelta(days=delta)


def _observed(holiday: date) -> date:
    """Apply Sunday→Monday observance rule (Saturday observed on Saturday)."""
    if holiday.weekday() == _SUNDAY:
        return holiday + timedelta(days=1)
    return holiday


def federal_holidays(year: int) -> set[date]:
    """Return the eleven observed US federal holidays for ``year``."""
    holidays = {
        date(year, 1, 1),                            # New Year's Day
        _nth_weekday_of_month(year, 1, 0, 3),         # MLK (3rd Mon Jan)
        _nth_weekday_of_month(year, 2, 0, 3),         # Washington's Birthday (3rd Mon Feb)
        _last_weekday_of_month(year, 5, 0),           # Memorial Day (last Mon May)
        date(year, 6, 19),                            # Juneteenth
        date(year, 7, 4),                             # Independence Day
        _nth_weekday_of_month(year, 9, 0, 1),         # Labor Day (1st Mon Sep)
        _nth_weekday_of_month(year, 10, 0, 2),        # Columbus Day (2nd Mon Oct)
        date(year, 11, 11),                           # Veterans Day
        _nth_weekday_of_month(year, 11, 3, 4),        # Thanksgiving (4th Thu Nov)
        date(year, 12, 25),                           # Christmas
    }
    return {_observed(h) for h in holidays}


def is_business_day(d: date) -> bool:
    # Per CFPB Reg Z §1026.19(f): Saturdays count, Sundays don't.
    if d.weekday() == _SUNDAY:
        return False
    if d in federal_holidays(d.year):
        return False
    return True


def add_three_business_days(issued_at_utc: datetime) -> datetime:
    """Return the moment (00:00:00 UTC on the third counted business day).

    Counting starts on the day after ``issued_at``.
    """
    d = issued_at_utc.astimezone(timezone.utc).date() + timedelta(days=1)
    counted = 0
    while True:
        if is_business_day(d):
            counted += 1
            if counted == 3:
                return datetime.combine(d, time(0, 0, 0), tzinfo=timezone.utc)
        d += timedelta(days=1)


def emd_credited_total(deposits: Iterable[dict]) -> Decimal:
    total = Decimal("0")
    for d in deposits:
        if d.get("status") == "HELD":
            total += Decimal(str(d.get("amount", 0)))
    return total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
