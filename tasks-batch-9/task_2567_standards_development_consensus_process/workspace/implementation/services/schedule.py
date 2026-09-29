"""Periodic review schedule and appeal timeliness (PRD 3.8, 3.9)."""

import datetime as _dt

from core.util import plus_days, plus_years

REVIEW_CYCLE_YEARS = 5
REVIEW_LEAD_DAYS = 180
REVIEW_GRACE_DAYS = 90
APPEAL_WINDOW_DAYS = 30


def due_date_from(anchor_date):
    """Five calendar years after the anchor, same month and day; a 29 February
    anchor falls back to 28 February."""
    return plus_years(anchor_date, REVIEW_CYCLE_YEARS)


def window_opens_on(due_date):
    return due_date - _dt.timedelta(days=REVIEW_LEAD_DAYS)


def grace_ends_on(due_date):
    return due_date + _dt.timedelta(days=REVIEW_GRACE_DAYS)


def appeal_deadline(anchor_instant):
    return plus_days(anchor_instant, APPEAL_WINDOW_DAYS)
