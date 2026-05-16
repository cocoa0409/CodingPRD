"""SEP event arithmetic — window_opens_on, window_closes_on, effective_date."""

from datetime import datetime, timedelta

from .dates import (
    parse_iso_date,
    parse_iso_datetime,
    first_of_month,
    first_day_of_next_month,
    iso_date_str,
    add_days,
)


def compute_sep_dates(event_type: str, event_date_str: str, reported_at_str: str):
    """Return (window_opens_on, window_closes_on, effective_date) all as YYYY-MM-DD."""
    event_date = parse_iso_date(event_date_str)
    reported_at_dt = parse_iso_datetime(reported_at_str)
    reported_date = reported_at_dt.date()

    if event_type in ("BIRTH_ADOPTION", "MARRIAGE"):
        window_opens_on = event_date
        effective_date = event_date

    elif event_type in ("LOSS_OF_COVERAGE", "MEDICAID_LOSS"):
        window_opens_on = event_date
        effective_date = first_day_of_next_month(reported_date)

    elif event_type == "MOVE":
        window_opens_on = event_date
        if reported_date <= add_days(event_date, 60):
            effective_date = first_day_of_next_month(reported_date)
        else:
            capped_anchor = add_days(event_date, 60)
            effective_date = first_day_of_next_month(capped_anchor)

    elif event_type == "INCOME_CHANGE":
        next_month = first_day_of_next_month(reported_date)
        window_opens_on = next_month
        effective_date = first_day_of_next_month(reported_date)

    elif event_type == "GAINED_CITIZENSHIP":
        window_opens_on = event_date
        effective_date = first_day_of_next_month(reported_date)

    else:
        # Defensive fallback
        window_opens_on = event_date
        effective_date = event_date

    window_closes_on = add_days(window_opens_on, 60)
    return iso_date_str(window_opens_on), iso_date_str(window_closes_on), iso_date_str(effective_date)
