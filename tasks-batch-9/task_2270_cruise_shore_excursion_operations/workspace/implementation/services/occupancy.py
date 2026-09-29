"""Meeting-point occupancy sweep (PRD 3.4, ladder priority 39)."""

from datetime import timedelta

from db import db
from errors import fail

MEETING_SETUP_MINUTES = 15
OCCUPANCY_FREE_STATUSES = ("CANCELLED_WEATHER", "CANCELLED_OPERATIONAL", "COMPLETED")


def occupation_window(meeting_time_utc, dispatch_dwell_minutes, slot_buffer_minutes):
    start = meeting_time_utc - timedelta(minutes=MEETING_SETUP_MINUTES)
    end = meeting_time_utc + timedelta(minutes=dispatch_dwell_minutes + slot_buffer_minutes)
    return start, end


def peer_windows(meeting_point, exclude_departure_id):
    windows = []
    for departure in db.departures.values():
        if departure["meeting_point_id"] != meeting_point["id"]:
            continue
        if exclude_departure_id is not None and departure["id"] == exclude_departure_id:
            continue
        if departure["status"] in OCCUPANCY_FREE_STATUSES:
            continue
        windows.append(occupation_window(departure["meeting_time_utc"],
                                        departure["dispatch_dwell_minutes"],
                                        meeting_point["slot_buffer_minutes"]))
    return windows


def check_congestion(meeting_point, meeting_time_utc, dispatch_dwell_minutes, exclude_departure_id=None):
    """Sweep the candidate window with its peers and refuse a peak above the limit."""
    candidate = occupation_window(meeting_time_utc, dispatch_dwell_minutes,
                                  meeting_point["slot_buffer_minutes"])
    peers = peer_windows(meeting_point, exclude_departure_id)

    instants = [candidate[0]]
    for start, _end in peers:
        if candidate[0] <= start < candidate[1]:
            instants.append(start)

    peak = 0
    for instant in instants:
        covering = 1  # the candidate itself covers every instant considered
        for start, end in peers:
            if start <= instant < end:
                covering += 1
        peak = max(peak, covering)

    if peak > meeting_point["max_concurrent_groups"]:
        fail("ERR_MEETING_POINT_CONGESTED",
             "the meeting point would exceed its concurrent group limit")
