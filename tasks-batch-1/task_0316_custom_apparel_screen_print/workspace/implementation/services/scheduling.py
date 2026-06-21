"""Machine availability checks for ProductionRun windows (PRD §3.2, §3.7).

Press (SCREEN_PRINT): buffered adjacency. A new run is rejected when its window
starts within teardown_buffer_min minutes AFTER a prior non-terminal run's
window_end, or ends within teardown_buffer_min minutes BEFORE a prior run's
window_start -> ERR_PRESS_WINDOW_CONFLICT.

EmbroideryStation (EMBROIDERY): half-open [start,end) overlap concurrency.
Touching adjacency (gap == 0) is allowed; the count of non-terminal runs whose
windows overlap a new run may not exceed head_count -> ERR_STATION_OVERSUBSCRIBED.

Only non-terminal runs (SCHEDULED, RUNNING) occupy a machine; ABORTED/COMPLETED
free their window.
"""
from db import store
from errors import err

NON_TERMINAL_RUN = {"SCHEDULED", "RUNNING"}


def _other_runs_on_press(press_id, exclude_run_id=None):
    out = []
    for r in store.production_runs.values():
        if r.get("press_id") != press_id:
            continue
        if r["status"] not in NON_TERMINAL_RUN:
            continue
        if exclude_run_id is not None and r["id"] == exclude_run_id:
            continue
        out.append(r)
    return out


def _other_runs_on_station(station_id, exclude_run_id=None):
    out = []
    for r in store.production_runs.values():
        if r.get("embroidery_station_id") != station_id:
            continue
        if r["status"] not in NON_TERMINAL_RUN:
            continue
        if exclude_run_id is not None and r["id"] == exclude_run_id:
            continue
        out.append(r)
    return out


def check_press_window(press, new_start, new_end):
    """Raise ERR_PRESS_WINDOW_CONFLICT on buffered-adjacency conflict."""
    buffer_seconds = press["teardown_buffer_min"] * 60
    for r in _other_runs_on_press(press["id"]):
        prior_start = _dt(r["window_start"])
        prior_end = _dt(r["window_end"])
        # New run starts within buffer AFTER a prior run's end.
        starts_too_soon = prior_end <= new_start < _add(prior_end, buffer_seconds)
        # New run ends within buffer BEFORE a prior run's start.
        ends_too_close = _sub(prior_start, buffer_seconds) < new_end <= prior_start
        # Direct overlap is also a conflict (buffer subsumes adjacency but
        # overlapping windows must be rejected too).
        overlaps = new_start < prior_end and prior_start < new_end
        if starts_too_soon or ends_too_close or overlaps:
            raise err("ERR_PRESS_WINDOW_CONFLICT", "Press window conflict")


def check_station_window(station, new_start, new_end):
    """Raise ERR_STATION_OVERSUBSCRIBED when overlapping non-terminal runs would
    exceed head_count (the new run inclusive)."""
    head_count = station["head_count"]
    overlapping = 0
    for r in _other_runs_on_station(station["id"]):
        prior_start = _dt(r["window_start"])
        prior_end = _dt(r["window_end"])
        # Half-open overlap; touching (gap == 0) is NOT an overlap.
        if new_start < prior_end and prior_start < new_end:
            overlapping += 1
    if overlapping + 1 > head_count:
        raise err("ERR_STATION_OVERSUBSCRIBED", "Embroidery station oversubscribed")


# --- datetime helpers -----------------------------------------------------------

def _dt(iso):
    from clock import parse_iso8601
    return parse_iso8601(iso)


def _add(dt, seconds):
    from datetime import timedelta
    return dt + timedelta(seconds=seconds)


def _sub(dt, seconds):
    from datetime import timedelta
    return dt - timedelta(seconds=seconds)
