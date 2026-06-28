"""Logical-clock date arithmetic helpers."""
from clock import parse_iso8601


def add_months(dt, months):
    """Add whole months to an aware datetime, clamping day-of-month overflow."""
    month_index = dt.month - 1 + months
    year = dt.year + month_index // 12
    month = month_index % 12 + 1
    # clamp day to last valid day of the target month
    day = dt.day
    while True:
        try:
            return dt.replace(year=year, month=month, day=day)
        except ValueError:
            day -= 1
            if day < 1:
                raise


def whole_months_between(start_dt, end_dt):
    """Whole months from start to end, floored. Negative -> handled by caller."""
    if end_dt < start_dt:
        return 0
    months = (end_dt.year - start_dt.year) * 12 + (end_dt.month - start_dt.month)
    # if the day/time in end hasn't reached the anchor day/time, drop a month
    anchor = add_months(start_dt, months)
    if anchor > end_dt:
        months -= 1
    return max(0, months)


def whole_days_between(start_dt, end_dt):
    """Floor of elapsed days from start to end; min 0."""
    if end_dt <= start_dt:
        return 0
    return (end_dt - start_dt).days


def parse(iso):
    if iso is None:
        return None
    return parse_iso8601(iso)
