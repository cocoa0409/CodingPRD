"""Minimal calendar-month arithmetic (no external dependency)."""
import calendar


def add_months(dt, months):
    """Return dt shifted forward by `months` calendar months (clamping day)."""
    month_index = dt.month - 1 + months
    year = dt.year + month_index // 12
    month = month_index % 12 + 1
    last_day = calendar.monthrange(year, month)[1]
    day = min(dt.day, last_day)
    return dt.replace(year=year, month=month, day=day)
