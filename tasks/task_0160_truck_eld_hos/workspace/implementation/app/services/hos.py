"""Hours-of-Service calculations (SCAFFOLD §1.3).

These pure functions consume the driver's ACTIVE DutyEvent history and return
minutes-remaining values for the three FMCSA limits, plus the sleeper-berth
pair qualification check.

All inputs are UTC datetimes; all outputs are integer minutes (truncated
toward zero per PRD §2.6).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

from ..timeutil import parse_iso


# ---- Constants (SCAFFOLD §1.3) ----
BASE_DRIVING_MINUTES = 660            # 11 hours
ADVERSE_EXTRA_MINUTES = 120           # 2 hours
QUALIFYING_BREAK_MINUTES = 600        # 10 hours
BASE_WINDOW_MINUTES = 840             # 14 hours
SEVENTY_HOUR_CAP_MINUTES = 4200       # 70 hours
SIXTY_HOUR_CAP_MINUTES = 3600         # 60 hours
RESTART_MIN_MINUTES = 2040            # 34 hours
SB_LONG_LEG_MIN = 420                 # 7 hours
SB_SHORT_LEG_MIN = 120                # 2 hours
SB_COMBINED_MIN = 600                 # 10 hours

OFF_DUTY_STATES = {"OFF_DUTY", "SLEEPER_BERTH"}
ON_DUTY_STATES = {"DRIVING", "ON_DUTY_NOT_DRIVING", "YARD_MOVES"}


def _active_sorted(events: List[dict]) -> List[dict]:
    """Return only ACTIVE events, sorted by event_time ascending."""
    out = [e for e in events if e.get("edit_state", "ACTIVE") == "ACTIVE"]
    out.sort(key=lambda e: parse_iso(e["event_time"]))
    return out


def _status_at_time(events: List[dict], t: datetime) -> Optional[str]:
    """Return the driver's status at instant *t* (assumes events sorted asc).

    Returns the new_status of the latest event with event_time <= t, or None
    if no event precedes t.
    """
    cur = None
    for e in events:
        if parse_iso(e["event_time"]) <= t:
            cur = e["new_status"]
        else:
            break
    return cur


def build_status_intervals(
    events: List[dict],
    horizon: datetime,
) -> List[Tuple[datetime, datetime, str]]:
    """Build (start, end, status) intervals from ACTIVE events up to *horizon*.

    The interval for event *i* is [event_time_i, event_time_{i+1}) with the
    final interval clipped at *horizon*.
    """
    sorted_events = _active_sorted(events)
    intervals: List[Tuple[datetime, datetime, str]] = []
    for i, e in enumerate(sorted_events):
        start = parse_iso(e["event_time"])
        if start >= horizon:
            break
        if i + 1 < len(sorted_events):
            end = parse_iso(sorted_events[i + 1]["event_time"])
        else:
            end = horizon
        if end > horizon:
            end = horizon
        if end <= start:
            continue
        intervals.append((start, end, e["new_status"]))
    return intervals


def continuous_off_duty_minutes_ending_at(
    events: List[dict], t: datetime
) -> int:
    """Continuous OFF_DUTY+SLEEPER_BERTH minutes ending exactly at *t*.

    Walks the status interval chain backward from *t* and accumulates
    minutes while the status is OFF_DUTY or SLEEPER_BERTH.  Stops at the
    first non-rest interval.
    """
    intervals = build_status_intervals(events, t)
    if not intervals:
        return 0
    total = 0
    for start, end, status in reversed(intervals):
        if status in OFF_DUTY_STATES:
            total += int((end - start).total_seconds() // 60)
        else:
            break
    return total


def most_recent_qualifying_break_end(
    events: List[dict], t: datetime
) -> Optional[datetime]:
    """Latest instant T <= t such that continuous rest ending at T >= 600 minutes.

    Returns None if no such instant exists.  We walk through interval
    boundaries; the qualifying break ends either at a boundary or at *t*
    itself (if rest is currently ongoing at *t*).
    """
    intervals = build_status_intervals(events, t)
    if not intervals:
        return None

    # Reduce to consecutive rest runs.
    best: Optional[datetime] = None
    i = 0
    while i < len(intervals):
        start, end, status = intervals[i]
        if status in OFF_DUTY_STATES:
            j = i
            run_start = start
            run_end = end
            while j + 1 < len(intervals) and intervals[j + 1][2] in OFF_DUTY_STATES:
                j += 1
                run_end = intervals[j][1]
            length = int((run_end - run_start).total_seconds() // 60)
            if length >= QUALIFYING_BREAK_MINUTES:
                # The break "completes" at the moment 600 min after run_start,
                # but the most recent qualifying break END is run_end.
                # Latest qualifying break end is the run's end (most recent).
                if best is None or run_end > best:
                    best = run_end
            i = j + 1
        else:
            i += 1
    return best


def driving_minutes_in_interval(
    events: List[dict], start: datetime, end: datetime
) -> int:
    """Sum DRIVING minutes from ACTIVE intervals intersected with [start, end)."""
    if end <= start:
        return 0
    intervals = build_status_intervals(events, end)
    total = 0
    for s, e, status in intervals:
        if status != "DRIVING":
            continue
        ovl_s = max(s, start)
        ovl_e = min(e, end)
        if ovl_e > ovl_s:
            total += int((ovl_e - ovl_s).total_seconds() // 60)
    return total


def on_duty_minutes_in_interval(
    events: List[dict], start: datetime, end: datetime
) -> int:
    """Sum DRIVING+ON_DUTY_NOT_DRIVING+YARD_MOVES minutes in [start, end)."""
    if end <= start:
        return 0
    intervals = build_status_intervals(events, end)
    total = 0
    for s, e, status in intervals:
        if status not in ON_DUTY_STATES:
            continue
        ovl_s = max(s, start)
        ovl_e = min(e, end)
        if ovl_e > ovl_s:
            total += int((ovl_e - ovl_s).total_seconds() // 60)
    return total


def available_driving_hours_minutes(
    events: List[dict],
    at_time: datetime,
    adverse_extended: bool,
) -> int:
    """Compute driving minutes remaining at *at_time*.

    Returns minutes (may be negative if overage).
    """
    break_end = most_recent_qualifying_break_end(events, at_time)
    if break_end is None:
        # No qualifying break has ever occurred — start counting from the
        # earliest event (or treat the available driving from "infinity ago").
        # In practice with no prior driving the result is the cap.
        sorted_events = _active_sorted(events)
        if not sorted_events:
            base = BASE_DRIVING_MINUTES + (ADVERSE_EXTRA_MINUTES if adverse_extended else 0)
            return base
        break_end = parse_iso(sorted_events[0]["event_time"])
    driving_used = driving_minutes_in_interval(events, break_end, at_time)
    cap = BASE_DRIVING_MINUTES + (ADVERSE_EXTRA_MINUTES if adverse_extended else 0)
    return cap - driving_used


def find_window_start(events: List[dict], at_time: datetime) -> Optional[datetime]:
    """Find the first ACTIVE event of an on-duty status after the most recent
    qualifying break (the 14-hour window anchor)."""
    break_end = most_recent_qualifying_break_end(events, at_time)
    sorted_events = _active_sorted(events)
    for e in sorted_events:
        t = parse_iso(e["event_time"])
        if t > at_time:
            break
        if break_end is not None and t < break_end:
            continue
        if e["new_status"] in ON_DUTY_STATES:
            return t
    return None


def available_on_duty_window_minutes(
    events: List[dict],
    at_time: datetime,
    adverse_extended: bool,
) -> int:
    """14-hour wall-clock window minutes remaining at *at_time*."""
    window_start = find_window_start(events, at_time)
    cap = BASE_WINDOW_MINUTES + (ADVERSE_EXTRA_MINUTES if adverse_extended else 0)
    if window_start is None:
        return cap
    elapsed = int((at_time - window_start).total_seconds() // 60)
    return cap - elapsed


def cycle_hours_remaining_minutes(
    events: List[dict],
    at_time: datetime,
    cycle_type: str,
    last_34_hour_restart_completed_at_iso: Optional[str],
) -> int:
    """Cycle minutes remaining at *at_time*.

    cycle_type ∈ {SEVENTY_HOUR_EIGHT_DAY, SIXTY_HOUR_SEVEN_DAY}
    """
    if cycle_type == "SIXTY_HOUR_SEVEN_DAY":
        cap = SIXTY_HOUR_CAP_MINUTES
        rolling_start = at_time - timedelta(days=7)
    else:
        cap = SEVENTY_HOUR_CAP_MINUTES
        rolling_start = at_time - timedelta(days=8)

    effective_start = rolling_start
    if last_34_hour_restart_completed_at_iso:
        restart_at = parse_iso(last_34_hour_restart_completed_at_iso)
        if restart_at > rolling_start:
            effective_start = restart_at

    on_duty_used = on_duty_minutes_in_interval(events, effective_start, at_time)
    return cap - on_duty_used


def find_unbroken_rest_window_completed_before(
    events: List[dict],
    at_time: datetime,
) -> Optional[datetime]:
    """If a continuous OFF_DUTY+SLEEPER_BERTH window of >= 34h just closed at
    *at_time* (i.e., the new event is the break-out from that rest), return
    the instant the window completed (which equals *at_time*).

    Specifically: we look at the contiguous rest interval ending exactly at
    *at_time* and return *at_time* if its length is >= 2040 minutes.
    """
    intervals = build_status_intervals(events, at_time)
    if not intervals:
        return None
    # Walk backward from the end accumulating rest minutes.
    total = 0
    for s, e, status in reversed(intervals):
        if e != at_time and status in OFF_DUTY_STATES:
            # We've already advanced past the last rest run — only the run
            # ending at at_time matters here.
            pass
        if status in OFF_DUTY_STATES:
            total += int((e - s).total_seconds() // 60)
        else:
            break
    if total >= RESTART_MIN_MINUTES:
        return at_time
    return None


# ---- Sleeper berth pair qualification ----

def sleeper_berth_pair_qualifies(
    events: List[dict],
    at_time: datetime,
) -> bool:
    """Evaluate the sleeper-berth pair rule (SCAFFOLD §1.3 sleeper_berth_pair_qualifies)."""
    intervals = build_status_intervals(events, at_time)
    if not intervals:
        return False

    # Step 1: find the most recent unbroken SLEEPER_BERTH run ending at at_time
    # with length >= 420 minutes.
    long_leg_start: Optional[datetime] = None
    long_leg_end: Optional[datetime] = None

    # Walk backward; the run ending at at_time must be pure SLEEPER_BERTH.
    sb_run_start = None
    sb_run_end = None
    for s, e, status in reversed(intervals):
        if status == "SLEEPER_BERTH":
            if sb_run_end is None:
                sb_run_end = e
            sb_run_start = s
        else:
            break
    if sb_run_start is None or sb_run_end is None:
        return False
    long_len = int((sb_run_end - sb_run_start).total_seconds() // 60)
    if long_len < SB_LONG_LEG_MIN:
        return False
    long_leg_start = sb_run_start
    long_leg_end = sb_run_end

    # Lookback restricted to last 36 hours per scaffold.
    lookback_horizon = at_time - timedelta(hours=36)

    # Step 2: find the most recent unbroken OFF_DUTY-or-SLEEPER_BERTH run ending
    # at or before long_leg_start (E2 <= S1) with length >= 120.
    # Build intervals up to long_leg_start.
    short_intervals = build_status_intervals(events, long_leg_start)
    if not short_intervals:
        return False
    # Walk backward from long_leg_start collecting rest runs.
    found_short_leg = False
    i = len(short_intervals) - 1
    while i >= 0:
        s, e, status = short_intervals[i]
        if status in OFF_DUTY_STATES:
            run_start = s
            run_end = e
            j = i
            while j - 1 >= 0 and short_intervals[j - 1][2] in OFF_DUTY_STATES:
                j -= 1
                run_start = short_intervals[j][0]
            length = int((run_end - run_start).total_seconds() // 60)
            if (
                length >= SB_SHORT_LEG_MIN
                and run_end <= long_leg_start
                and run_start >= lookback_horizon
            ):
                if long_len + length >= SB_COMBINED_MIN:
                    found_short_leg = True
                    break
            i = j - 1
        else:
            i -= 1
    return found_short_leg
