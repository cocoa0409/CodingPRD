"""Fiscal year derivation and study window computation."""

from datetime import date


def fiscal_year_for_date(d, end_month):
    """Derive fiscal-year label from a date and fiscal_year_end_month."""
    if isinstance(d, str):
        d = date.fromisoformat(d)
    if end_month == 12:
        return d.year
    return d.year + 1 if d.month > end_month else d.year


def study_window(fiscal_year, end_month):
    """Return (window_start_date, window_end_date_exclusive) as YYYY-MM-DD strings."""
    if end_month == 12:
        start = date(fiscal_year, 1, 1)
        end = date(fiscal_year + 1, 1, 1)
    else:
        start = date(fiscal_year - 1, end_month + 1, 1)
        end = date(fiscal_year, end_month + 1, 1)
    return start.isoformat(), end.isoformat()


def windows_overlap(s1, e1, s2, e2):
    """Check if two half-open intervals [s1,e1) and [s2,e2) overlap."""
    return s1 < e2 and s2 < e1
