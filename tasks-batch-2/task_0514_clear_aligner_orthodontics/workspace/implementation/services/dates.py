"""Calendar date arithmetic helpers."""
from datetime import timedelta


def add_weeks(dt, weeks):
    return dt + timedelta(weeks=weeks)


def add_months(dt, months):
    """Add a whole number of calendar months to a datetime, clamping the day to
    the last valid day of the target month (e.g. Jan 31 + 1 month -> Feb 28/29)."""
    month_index = dt.month - 1 + months
    year = dt.year + month_index // 12
    month = month_index % 12 + 1
    # clamp day to the last day of the target month
    if month == 12:
        next_month_year, next_month = year + 1, 1
    else:
        next_month_year, next_month = year, month + 1
    from datetime import datetime
    first_of_next = datetime(next_month_year, next_month, 1, tzinfo=dt.tzinfo)
    last_day = (first_of_next - timedelta(days=1)).day
    day = min(dt.day, last_day)
    return dt.replace(year=year, month=month, day=day)
