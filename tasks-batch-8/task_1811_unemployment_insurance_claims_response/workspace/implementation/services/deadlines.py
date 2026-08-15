"""Deadline arithmetic (PRD §2.6): day counting, federal holidays, weekend
shift, and the 17:00:00Z end-of-day pin."""
from datetime import date, datetime, timedelta, timezone

UTC = timezone.utc

FEDERAL_HOLIDAYS = {
    date(2026, 1, 1),
    date(2026, 1, 19),
    date(2026, 2, 16),
    date(2026, 5, 25),
    date(2026, 6, 19),
    date(2026, 7, 3),
    date(2026, 9, 7),
    date(2026, 10, 12),
    date(2026, 11, 11),
    date(2026, 11, 26),
    date(2026, 12, 25),
}

END_OF_DAY_HOUR = 17


def _pin_eod(d):
    """Pin a calendar date to 17:00:00 UTC."""
    return datetime(d.year, d.month, d.day, END_OF_DAY_HOUR, 0, 0, tzinfo=UTC)


def _is_business_day(d):
    return d.weekday() < 5 and d not in FEDERAL_HOLIDAYS


def _apply_weekend_shift(d, weekend_shift):
    if weekend_shift == "NEXT_BUSINESS_DAY":
        while not _is_business_day(d):
            d += timedelta(days=1)
    return d


def response_due_at(notice_received_dt, rule):
    """response_deadline_computation (§1.3): base = date part of
    notice_received_at; CALENDAR adds every day; BUSINESS counts only
    Mon-Fri non-holidays; weekend_shift post-processes both; pinned 17:00Z."""
    base = notice_received_dt.date()
    if rule["window_basis"] == "CALENDAR":
        due = base + timedelta(days=rule["response_window_days"])
    else:  # BUSINESS
        due = base
        remaining = rule["response_window_days"]
        while remaining > 0:
            due += timedelta(days=1)
            if _is_business_day(due):
                remaining -= 1
    due = _apply_weekend_shift(due, rule["weekend_shift"])
    return _pin_eod(due)


def calendar_window_due(anchor_dt, window_days, rule):
    """Appeal and protest windows: always calendar days from the anchor's date
    part, weekend_shift applied, pinned to 17:00:00Z."""
    due = anchor_dt.date() + timedelta(days=window_days)
    due = _apply_weekend_shift(due, rule["weekend_shift"])
    return _pin_eod(due)


def timeliness(filed_dt, due_dt):
    """deadline_boundary_check (§1.3): inclusive boundary at second
    granularity — filed_at exactly == due_at is ON_TIME."""
    return "ON_TIME" if filed_dt <= due_dt else "LATE"
