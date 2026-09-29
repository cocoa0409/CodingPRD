"""Occupancy and continuing-operations temporal rules (PRD section 2.10)."""

from datetime import timedelta

from store import store, windows_of

LIVE_WINDOW_STATUSES = ("SCHEDULED", "BLOCKED_STALE_DESIGN", "IN_PROGRESS")
BAY_OCCUPYING_STATUSES_EXCLUDED = ("SCRAPPED", "INSTALLED")


def protected_shift_collision(zone, start_dt, end_dt):
    """The window [start, end) must miss every daily occurrence of the zone's
    protected shift [start_minute, end_minute).  Touching endpoints are fine."""
    shift_start = zone["protected_shift_start_minute"]
    shift_end = zone["protected_shift_end_minute"]
    if shift_end <= shift_start:
        return False
    if end_dt <= start_dt:
        return False
    if (end_dt - start_dt) >= timedelta(days=1):
        # Any interval of a full day or longer contains a whole occurrence.
        return True
    midnight = start_dt.replace(hour=0, minute=0, second=0, microsecond=0)
    for day_offset in (-1, 0, 1, 2):
        day = midnight + timedelta(days=day_offset)
        occurrence_start = day + timedelta(minutes=shift_start)
        occurrence_end = day + timedelta(minutes=shift_end)
        if max(start_dt, occurrence_start) < min(end_dt, occurrence_end):
            return True
    return False


def zone_window_overlap(zone, start_dt, end_dt, exclude_window_id=None):
    """Buffered separation on a site zone; half-open window intervals."""
    buffer_delta = timedelta(minutes=zone["buffer_minutes"])
    for window in windows_of(zone["project_id"]):
        if window["site_zone_id"] != zone["id"]:
            continue
        if exclude_window_id is not None and window["id"] == exclude_window_id:
            continue
        if window["status"] not in LIVE_WINDOW_STATUSES:
            continue
        existing_start = window["_start_dt"]
        existing_end = window["_end_dt"]
        if start_dt < existing_end + buffer_delta and existing_start < end_dt + buffer_delta:
            return True
    return False


def staging_bay_capacity_exceeded(bay, start_dt, end_dt):
    """Closed occupancy intervals: two lots that merely touch are both present."""
    intervals = []
    for lot in store.fabrication_lots.values():
        if lot["staging_bay_id"] != bay["id"]:
            continue
        if lot["status"] in BAY_OCCUPYING_STATUSES_EXCLUDED:
            continue
        intervals.append((lot["_occ_start_dt"], lot["_occ_end_dt"]))
    intervals.append((start_dt, end_dt))
    for instant, _ in intervals:
        covering = sum(1 for begin, finish in intervals if begin <= instant <= finish)
        if covering > bay["concurrent_capacity"]:
            return True
    return False
