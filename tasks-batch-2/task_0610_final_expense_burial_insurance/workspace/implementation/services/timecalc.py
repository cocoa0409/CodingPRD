"""Calendar arithmetic helpers measured against the logical clock.

All of these operate on timezone-aware UTC datetimes produced by clock.parse_iso.
"""


def whole_days_between(start, end):
    """Whole days from start to end, floored at 0 (integer day count)."""
    if start is None or end is None:
        return 0
    delta = end - start
    days = delta.days  # timedelta.days floors toward negative infinity
    if days < 0:
        return 0
    return days


def whole_years_between(start, end):
    """Whole policy-years (anniversaries fully elapsed) from start to end, floored at 0.

    A full policy-year elapses on each issue-date anniversary. E.g. issue
    2026-01-01, clock 2029-01-01 -> 3 whole years; clock 2028-12-31 -> 2.
    """
    if start is None or end is None:
        return 0
    if end < start:
        return 0
    years = end.year - start.year
    # Subtract one if the anniversary in `end.year` has not yet been reached.
    anniversary = _safe_replace_year(start, start.year + years)
    if anniversary > end:
        years -= 1
    if years < 0:
        years = 0
    return years


def whole_months_between(start, end):
    """Whole calendar months from start to end, floored at 0.

    A full month elapses when the day-of-month boundary (and time) of `start`
    is reached or passed. E.g. issue 2026-01-15, death 2026-03-15 -> 2 months;
    death 2026-03-14 -> 1 month.
    """
    if start is None or end is None:
        return 0
    if end < start:
        return 0
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if months <= 0:
        return max(0, months)
    anniversary = _add_months(start, months)
    if anniversary > end:
        months -= 1
    if months < 0:
        months = 0
    return months


def _safe_replace_year(dt, year):
    try:
        return dt.replace(year=year)
    except ValueError:
        # Feb 29 -> Feb 28 on non-leap target years.
        return dt.replace(year=year, day=28)


def _add_months(dt, months):
    total = dt.month - 1 + months
    year = dt.year + total // 12
    month = total % 12 + 1
    day = dt.day
    while True:
        try:
            return dt.replace(year=year, month=month, day=day)
        except ValueError:
            day -= 1
            if day < 1:
                raise
