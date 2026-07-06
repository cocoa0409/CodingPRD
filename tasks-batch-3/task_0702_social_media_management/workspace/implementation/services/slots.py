"""Schedule-slot temporal geometry (PRD §3.2).

A slot occupies the half-open window [slot_start_utc, slot_start_utc+duration).
A new slot must not overlap any RESERVED or FIRED slot on the same channel, and
must be separated from the nearest such slot by at least min_publish_gap_minutes.
"""
from datetime import datetime, timezone

from errors import err, ERR_INVALID_REQUEST


def parse_utc(value):
    """Parse an ISO 8601 UTC instant into an aware datetime.

    Accepts a trailing 'Z' or an explicit offset. Raises ERR_INVALID_REQUEST on a
    malformed value.
    """
    if not isinstance(value, str) or not value.strip():
        raise err(ERR_INVALID_REQUEST, "slot_start_utc must be an ISO 8601 string")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        raise err(ERR_INVALID_REQUEST, "slot_start_utc is not a valid ISO 8601 instant")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def windows_overlap(a_start, a_end, b_start, b_end):
    """True iff two half-open intervals [start, end) overlap."""
    return a_start < b_end and b_start < a_end


def gap_minutes(a_start, a_end, b_start, b_end):
    """Minutes between two non-overlapping intervals (0 if touching/overlapping)."""
    if windows_overlap(a_start, a_end, b_start, b_end):
        return 0.0
    if a_end <= b_start:
        delta = (b_start - a_end).total_seconds()
    else:
        delta = (a_start - b_end).total_seconds()
    return delta / 60.0
