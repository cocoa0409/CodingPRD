"""Pinned calculations from PRD §2.9 / §3.6 / §3.7 and SCAFFOLD §1.3."""
from decimal import Decimal, ROUND_HALF_UP
from datetime import timedelta


PFL_QUOTA_HOURS = {
    "CA": 320,
    "NY": 480,
    "NJ": 480,
    "MA": 480,
    "WA": 480,
    "CT": 480,
    "RI": 200,
    "CO": 480,
    "OR": 480,
    "FED": 0,
}

FMLA_ANNUAL_QUOTA_HOURS = 480


def _to_decimal(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round_half_up_1dp(value):
    """Round half-up to 1 decimal place; return Decimal."""
    v = _to_decimal(value)
    return v.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def round_half_up_4dp(value):
    v = _to_decimal(value)
    return v.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def round_half_up_cents(value):
    v = _to_decimal(value)
    return int(v.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def floor_months_between(hire_date, requested_start_at):
    """floor((requested_start_at - hire_date) days / 30) — integer."""
    delta = requested_start_at - hire_date
    days = delta.days
    if days < 0:
        return 0
    return days // 30


def fmla_eligibility(employee, leave_case):
    """Return (eligible, tenure_months, hours_at_request)."""
    tenure_months = floor_months_between(employee["hire_date"], leave_case["requested_start_at"])
    hours = employee["hours_worked_trailing_12mo"]
    eligible = (tenure_months >= 12) and (hours >= 1250)
    return eligible, tenure_months, hours


def compute_pool_charge(raw_hours, fmla_charged_pre, pfl_charged_pre,
                        pfl_concurrent, home_state_code):
    """
    fmla_pfl_pool_charge — see PRD §3.6 / SCAFFOLD §1.3.

    Evaluation order pinned:
      1) FMLA first: fmla_charge = min(raw_hours, fmla_remaining)
      2) PFL derived from fmla_charge: pfl_charge = min(fmla_charge, pfl_remaining)
         (PFL only ticks down alongside FMLA, never alone)
    Per-interval values rounded half-up to 1 decimal place.
    """
    raw = _to_decimal(raw_hours)
    fmla_pre = _to_decimal(fmla_charged_pre)
    pfl_pre = _to_decimal(pfl_charged_pre)

    fmla_remaining = Decimal(FMLA_ANNUAL_QUOTA_HOURS) - fmla_pre
    if fmla_remaining < 0:
        fmla_remaining = Decimal(0)
    fmla_charge = min(raw, fmla_remaining)

    if pfl_concurrent:
        pfl_quota = Decimal(PFL_QUOTA_HOURS.get(home_state_code, 0))
        pfl_remaining = pfl_quota - pfl_pre
        if pfl_remaining < 0:
            pfl_remaining = Decimal(0)
        pfl_charge = min(fmla_charge, pfl_remaining)
    else:
        pfl_charge = Decimal(0)

    fmla_charge = round_half_up_1dp(fmla_charge)
    pfl_charge = round_half_up_1dp(pfl_charge)
    return fmla_charge, pfl_charge


def count_business_days(start_dt, end_dt):
    """Count weekdays (Mon-Fri) in half-open [start_dt, end_dt).

    Operates on calendar-date granularity: each calendar date within the range
    counts if it's Mon-Fri. We treat the period as a span of calendar dates
    from start.date() (inclusive) to end.date() (exclusive when end is at
    midnight; otherwise inclusive up through end.date()).
    """
    if end_dt <= start_dt:
        return 0
    # Convert to UTC dates. Walk day by day from start_dt's date.
    cur_date = start_dt.date()
    end_date = end_dt.date()
    end_is_midnight = (end_dt.hour == 0 and end_dt.minute == 0 and
                       end_dt.second == 0 and end_dt.microsecond == 0)
    days = 0
    while cur_date < end_date:
        if cur_date.weekday() < 5:  # 0=Mon..4=Fri
            days += 1
        cur_date = cur_date + timedelta(days=1)
    if not end_is_midnight:
        # end_date itself partially included
        if end_date.weekday() < 5:
            days += 1
    return days


def _intersect_business_days(period_start, period_end, intervals):
    """Count business days in intersection of [period_start, period_end) with
    the union of (interval.start, interval.end) for each RECORDED interval."""
    # Build a set of in-period calendar dates that fall within any RECORDED interval.
    in_period_dates = set()
    cur = period_start.date()
    end_date = period_end.date()
    end_is_midnight = (period_end.hour == 0 and period_end.minute == 0 and
                       period_end.second == 0 and period_end.microsecond == 0)
    # We enumerate days the period covers.
    period_dates = []
    while cur < end_date:
        period_dates.append(cur)
        cur = cur + timedelta(days=1)
    if not end_is_midnight:
        period_dates.append(end_date)
    period_date_set = set(period_dates)

    for iv in intervals:
        if iv["status"] != "RECORDED":
            continue
        s = iv["start_datetime"]
        e = iv["end_datetime"]
        # Clip to period
        ps = max(s, period_start)
        pe = min(e, period_end)
        if pe <= ps:
            continue
        cur = ps.date()
        ed = pe.date()
        e_is_midnight = (pe.hour == 0 and pe.minute == 0 and pe.second == 0
                         and pe.microsecond == 0)
        while cur < ed:
            if cur in period_date_set:
                in_period_dates.add(cur)
            cur = cur + timedelta(days=1)
        if not e_is_midnight:
            if ed in period_date_set:
                in_period_dates.add(ed)

    # Now count business days (Mon-Fri) within those dates.
    return sum(1 for d in in_period_dates if d.weekday() < 5)


def benefit_continuation_premium(period_start, period_end,
                                 monthly_premium_total_cents,
                                 employer_premium_share_pct,
                                 recorded_intervals):
    """Pinned proration per PRD §3.7. Returns (employer_cents, employee_cents)."""
    period_business_days = count_business_days(period_start, period_end)
    if period_business_days == 0:
        return 0, 0
    leave_business_days = _intersect_business_days(period_start, period_end, recorded_intervals)
    leave_fraction = Decimal(leave_business_days) / Decimal(period_business_days)
    leave_fraction = round_half_up_4dp(leave_fraction)
    total = Decimal(monthly_premium_total_cents)
    pct = _to_decimal(employer_premium_share_pct)
    employer_share = round_half_up_cents(total * pct * leave_fraction)
    employee_share = round_half_up_cents(total * (Decimal(1) - pct) * leave_fraction)
    return employer_share, employee_share
