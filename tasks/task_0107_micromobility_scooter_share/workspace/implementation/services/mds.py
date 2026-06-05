"""MDS regulatory report aggregates (scaffold §1.3 mds_*, PRD §3.8).

trip_count            — COMPLETED trips whose started_at falls in the half-open
                        window [window_start, window_end).
total_billable_minutes— sum of billable_minutes over exactly those trips.
avg_available_vehicles— time-weighted average AVAILABLE-vehicle count across the
                        window, integrated over vehicle status-change events and
                        divided by window seconds, rounded half-up to 2 dp.
"""
from datetime import datetime, timezone

from db import db
from util import round_half_up_2dp


def parse_iso(value):
    """Parse an ISO 8601 instant into an aware UTC datetime, or None."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _trips_in_window(ws, we):
    """COMPLETED trips with ws <= started_at < we (half-open)."""
    out = []
    for trip in db.trips.values():
        if trip["status"] != "COMPLETED":
            continue
        started = parse_iso(trip.get("started_at"))
        if started is None:
            continue
        if ws <= started < we:
            out.append(trip)
    return out


def compute_aggregates(report):
    """Recompute the three aggregates for a report's window (PRD §3.8)."""
    ws = parse_iso(report["window_start"])
    we = parse_iso(report["window_end"])

    trips = _trips_in_window(ws, we)
    trip_count = len(trips)
    total_billable_minutes = sum(t.get("billable_minutes", 0) for t in trips)
    avg = _time_weighted_availability(ws, we)

    return {
        "trip_count": trip_count,
        "total_billable_minutes": total_billable_minutes,
        "avg_available_vehicles": avg,
    }


def _time_weighted_availability(ws, we):
    """Integrate AVAILABLE-vehicle count over [ws, we) / window_seconds (PRD §3.8)."""
    window_seconds = (we - ws).total_seconds()
    if window_seconds <= 0:
        return 0.0

    # Collect every status-change instant that falls strictly inside the window
    # as a breakpoint; together with ws and we these define sub-intervals over
    # which the AVAILABLE count is constant.
    breakpoints = {ws, we}
    for ev in db.vehicle_status_events:
        if ws < ev["at"] < we:
            breakpoints.add(ev["at"])
    points = sorted(breakpoints)

    total = 0.0
    for i in range(len(points) - 1):
        seg_start = points[i]
        seg_end = points[i + 1]
        seconds = (seg_end - seg_start).total_seconds()
        if seconds <= 0:
            continue
        count = _available_count_at(seg_start)
        total += count * seconds

    return round_half_up_2dp(total / window_seconds)


def _available_count_at(instant):
    """Number of vehicles whose status is AVAILABLE at `instant`.

    A vehicle's status at `instant` is the status from its most recent timeline
    event at or before `instant`. Vehicles registered after `instant` (no event
    at or before it) are not counted.
    """
    latest = {}  # vehicle_id -> (seq, status)
    for ev in db.vehicle_status_events:
        if ev["at"] <= instant:
            prev = latest.get(ev["vehicle_id"])
            if prev is None or ev["_seq"] > prev[0]:
                latest[ev["vehicle_id"]] = (ev["_seq"], ev["status"])
    return sum(1 for _, status in latest.values() if status == "AVAILABLE")
