"""Business calculations (SCAFFOLD §1.3): rent_reasonableness, hap_split,
abatement_proration, first_payment_schedule.

All money arithmetic uses integer cents; any fractional intermediate result is
rounded half-up to the nearest whole cent.
"""

from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
import calendar

import db


COMPARABLE_CAP_RATIO = Decimal("1.10")
COMPARABLE_RECENCY_MONTHS = 12
INCOME_RATIO = Decimal("0.30")


def _round_half_up_cents(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _parse_iso_date(s: str) -> date:
    """Parse YYYY-MM-DD into a date. Assumes well-formed input."""
    y, m, d = s.split("-")
    return date(int(y), int(m), int(d))


def _sub_months(d: date, months: int) -> date:
    """Subtract `months` calendar months from a date."""
    month = d.month - months
    year = d.year
    while month <= 0:
        month += 12
        year -= 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def find_payment_standard(zip_code: str, bedroom_count: int, target_date: date):
    """Find the applicable PaymentStandard for (zip, bedrooms, target_date).

    Match: effective_from <= target_date <= effective_to (or effective_to null).
    If multiple match, pick latest effective_from; ties broken by created_at ASC.
    Returns the row dict, or None.
    """
    matches = []
    for ps in db.payment_standards.values():
        if ps["zip_code"] != zip_code or ps["bedroom_count"] != bedroom_count:
            continue
        ef = _parse_iso_date(ps["effective_from"])
        et = _parse_iso_date(ps["effective_to"]) if ps.get("effective_to") else None
        if ef <= target_date and (et is None or target_date <= et):
            matches.append(ps)
    if not matches:
        return None
    # Latest effective_from wins; tie broken by created_at ASC.
    matches.sort(key=lambda r: r["created_at"])  # created_at ASC first
    matches.sort(key=lambda r: r["effective_from"], reverse=True)  # stable: keeps created_at order within same effective_from
    return matches[0]


def rent_reasonableness(contract_rent_cents: int, zip_code: str, bedroom_count: int,
                        target_date: date) -> int:
    """Compute approved rent per SCAFFOLD §1.3 rent_reasonableness.

    - comparables: same zip, same bedrooms, survey_date within 12 months
      preceding current logical date (inclusive).
    - if no comparables: approved = min(contract_rent, payment_standard.amount)
    - else: cap = min(payment_standard.amount, round_half_up(median * 1.10));
      approved = min(contract_rent, cap).
    """
    now_date = db.current_logical_date()
    cutoff = _sub_months(now_date, COMPARABLE_RECENCY_MONTHS)
    comps = []
    for rc in db.rent_comparables.values():
        if rc["zip_code"] != zip_code or rc["bedroom_count"] != bedroom_count:
            continue
        sd = _parse_iso_date(rc["survey_date"])
        if cutoff <= sd <= now_date:
            comps.append(rc["rent_cents"])

    ps = find_payment_standard(zip_code, bedroom_count, target_date)
    ps_amount = ps["amount_cents"] if ps else 0

    if not comps:
        return min(contract_rent_cents, ps_amount)

    comps.sort()
    n = len(comps)
    if n % 2 == 1:
        median = Decimal(comps[n // 2])
    else:
        median = (Decimal(comps[n // 2 - 1]) + Decimal(comps[n // 2])) / Decimal(2)
        median = median.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    cap_with_comps = _round_half_up_cents(median * COMPARABLE_CAP_RATIO)
    cap = min(ps_amount, cap_with_comps)
    return min(contract_rent_cents, cap)


def hap_split(approved_rent_cents: int, family_annual_income_cents: int,
              payment_standard_amount_cents: int):
    """Compute (tenant_portion_cents, hap_portion_cents) per SCAFFOLD §1.3 hap_split.

    tenant_minimum = round_half_up(income * 0.30 / 12)
    base_tenant    = max(tenant_minimum, approved_rent - payment_standard)
    tenant_portion = min(base_tenant, approved_rent)
    hap_portion    = approved_rent - tenant_portion
    """
    tenant_minimum = _round_half_up_cents(
        Decimal(family_annual_income_cents) * INCOME_RATIO / Decimal(12)
    )
    base_tenant = max(tenant_minimum, approved_rent_cents - payment_standard_amount_cents)
    tenant_portion = min(base_tenant, approved_rent_cents)
    hap_portion = approved_rent_cents - tenant_portion
    return tenant_portion, hap_portion


def _days_in_month(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]


def abatement_proration(hap_portion_cents: int, period_month: str,
                        abate_start: date, abate_end: date) -> int:
    """Compute new hap_amount_cents for one payment row per abatement_proration.

    period_month: 'YYYY-MM-01'
    abatement window: [abate_start, abate_end), start inclusive, end exclusive.
    deduction = round_half_up(hap_portion * abated_days / days_in_month)
    new = hap_portion - deduction; if abated_days == days_in_month, new = 0.
    """
    pm = _parse_iso_date(period_month)
    days_in_month = _days_in_month(pm.year, pm.month)
    month_start = date(pm.year, pm.month, 1)
    month_end_exclusive = month_start + timedelta(days=days_in_month)

    # Intersect [abate_start, abate_end) with [month_start, month_end_exclusive)
    window_start = max(abate_start, month_start)
    window_end = min(abate_end, month_end_exclusive)
    abated_days = max(0, (window_end - window_start).days)

    if abated_days >= days_in_month:
        return 0
    deduction = _round_half_up_cents(
        Decimal(hap_portion_cents) * Decimal(abated_days) / Decimal(days_in_month)
    )
    return hap_portion_cents - deduction


def first_payment_period(lease_start: date) -> date:
    """First HAPPayment period_month per first_payment_schedule.

    Day-of-month == 1 → first of that month; otherwise first of following month.
    """
    if lease_start.day == 1:
        return date(lease_start.year, lease_start.month, 1)
    # first of following month
    if lease_start.month == 12:
        return date(lease_start.year + 1, 1, 1)
    return date(lease_start.year, lease_start.month + 1, 1)


def add_one_year(d: date) -> date:
    """Anniversary: same month/day next year; Feb 29 → Feb 28 on non-leap years."""
    try:
        return date(d.year + 1, d.month, d.day)
    except ValueError:
        return date(d.year + 1, d.month, 28)
