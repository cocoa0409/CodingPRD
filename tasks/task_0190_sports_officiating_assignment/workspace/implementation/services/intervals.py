"""Half-open interval arithmetic (PRD §3.4).

A game occupies [start_utc, start_utc + duration_minutes), end exclusive.
Availability windows are half-open [start, end). Double-booking overlap is
closed-on-start, open-on-end: two intervals that merely touch at an endpoint
do NOT overlap.
"""
from datetime import timedelta

from timeutil import parse_iso


def game_interval(game):
    start = parse_iso(game["start_utc"])
    end = start + timedelta(minutes=int(game["duration_minutes"]))
    return start, end


def contains(window_start, window_end, inner_start, inner_end):
    """True iff [inner_start, inner_end) lies entirely inside
    [window_start, window_end) (half-open, end exclusive)."""
    return window_start <= inner_start and inner_end <= window_end


def overlaps(a_start, a_end, b_start, b_end):
    """True iff half-open intervals [a_start,a_end) and [b_start,b_end)
    overlap. Touching at an endpoint is NOT an overlap."""
    return a_start < b_end and b_start < a_end
