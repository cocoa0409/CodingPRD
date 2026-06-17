"""Interval reservation helpers (PRD §2.6).

Booth interval: [event_start - SETUP_BUFFER_MIN, event_end + TEARDOWN_BUFFER_MIN
+ TURNAROUND_BUFFER_MIN), HALF-OPEN — a new claim starting exactly on an
existing claim's end edge is allowed.

Attendant interval: [event_start - SETUP_BUFFER_MIN, event_end +
TEARDOWN_BUFFER_MIN], CLOSED, no turnaround buffer — touching at the boundary
conflicts.
"""
from datetime import timedelta

from services.calculations import (
    SETUP_BUFFER_MIN,
    TEARDOWN_BUFFER_MIN,
    TURNAROUND_BUFFER_MIN,
)


def booth_interval(event_start_dt, event_end_dt):
    start = event_start_dt - timedelta(minutes=SETUP_BUFFER_MIN)
    end = event_end_dt + timedelta(minutes=TEARDOWN_BUFFER_MIN + TURNAROUND_BUFFER_MIN)
    return start, end


def attendant_interval(event_start_dt, event_end_dt):
    start = event_start_dt - timedelta(minutes=SETUP_BUFFER_MIN)
    end = event_end_dt + timedelta(minutes=TEARDOWN_BUFFER_MIN)
    return start, end


def booth_overlaps(a_start, a_end, b_start, b_end):
    """Half-open overlap: two intervals [a_start,a_end) and [b_start,b_end)
    overlap when a_start < b_end and b_start < a_end."""
    return a_start < b_end and b_start < a_end


def attendant_overlaps(a_start, a_end, b_start, b_end):
    """Closed overlap: [a_start,a_end] and [b_start,b_end] overlap when
    a_start <= b_end and b_start <= a_end (touching boundary conflicts)."""
    return a_start <= b_end and b_start <= a_end
