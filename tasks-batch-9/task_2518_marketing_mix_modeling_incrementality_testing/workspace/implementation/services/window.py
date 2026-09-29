"""Data window period grid, alignment and coverage counters (PRD section 3.2)."""

from datetime import timedelta
from decimal import Decimal

import db as store
from errors import ApiError
from services.numeric import D, HUNDRED, q2

PERIOD_DAYS = {"WEEKLY": 7, "DAILY": 1}


def period_length(window):
    return PERIOD_DAYS[window["granularity"]]


def window_periods(window):
    start = window["_window_start_date"]
    step = period_length(window)
    return [start + timedelta(days=step * index)
            for index in range(window["expected_period_count"])]


def assert_period_aligned(window, period_date):
    """The period start must sit inside the half-open window and on the grid."""
    start = window["_window_start_date"]
    end = window["_window_end_date"]
    if period_date < start or period_date >= end:
        raise ApiError("ERR_PERIOD_NOT_ALIGNED",
                       "period_start_date lies outside the window's half-open interval.")
    offset_days = (period_date - start).days
    if offset_days % period_length(window) != 0:
        raise ApiError("ERR_PERIOD_NOT_ALIGNED",
                       "period_start_date is not on the window's period grid.")


def refresh_window_counts(window):
    live_spend = store.spend_of_window(window["id"])
    window["spend_observation_count"] = len(live_spend)
    sales = store.sales_of_window(window["id"])
    window["sales_period_count"] = len(sales)
    expected = window["expected_period_count"]
    if expected:
        window["lag_completeness_pct"] = q2(HUNDRED * D(len(sales)) / D(expected))
    else:
        window["lag_completeness_pct"] = Decimal("0.00")
    return window


def windows_overlap(a_start, a_end, b_start, b_end):
    """Closed-interval comparison with no buffer — touching endpoints conflict."""
    return a_start <= b_end and b_start <= a_end
