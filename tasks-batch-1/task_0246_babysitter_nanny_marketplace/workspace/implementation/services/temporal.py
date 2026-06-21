"""Temporal overlap detection (PRD §3.7, §3.8).

Sessions use half-open intervals [window_start, window_end). Two of a
caregiver's sessions conflict if they come within TRAVEL_BUFFER_MINUTES of one
another — a gap of at least the buffer must separate them.

Family first-session windows use closed adjacency with NO buffer: two windows
conflict whenever they share any instant.
"""

from datetime import timedelta

from db import store, parse_dt
from services.calc import TRAVEL_BUFFER_MINUTES

NON_TERMINAL_SESSION_STATES = {"SCHEDULED", "IN_PROGRESS"}


def _session_window(s):
    return parse_dt(s["window_start_iso"]), parse_dt(s["window_end_iso"])


def caregiver_has_buffered_overlap(caregiver_id, start_dt, end_dt, exclude_session_id=None):
    """True if [start, end) comes within the travel buffer of another
    non-terminal session of this caregiver.

    Buffer rule: two half-open intervals must be separated by >= buffer. They
    conflict if start_a < end_b + buffer AND start_b < end_a + buffer.
    """
    buf = timedelta(minutes=TRAVEL_BUFFER_MINUTES)
    for s in store.sessions.values():
        if s["caregiver_id"] != caregiver_id:
            continue
        if exclude_session_id is not None and s["id"] == exclude_session_id:
            continue
        if s["status"] not in NON_TERMINAL_SESSION_STATES:
            continue
        b_start, b_end = _session_window(s)
        if start_dt < b_end + buf and b_start < end_dt + buf:
            return True
    return False


def windows_share_instant(a_start, a_end, b_start, b_end):
    """Closed-adjacency overlap with no buffer: share any instant.

    Two windows conflict whenever they share any instant: a_start <= b_end and
    b_start <= a_end (closed on both ends).
    """
    return a_start <= b_end and b_start <= a_end
