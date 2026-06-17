"""Shared lookup, time-parsing, and time-overlap helpers."""

from datetime import datetime, timedelta, timezone

import errors
from db import db
from errors import err


def find_or_404(collection, resource_id):
    """Fetch a resource by id from the given dict or raise ERR_NOT_FOUND."""
    rec = collection.get(resource_id)
    if rec is None:
        raise err(errors.ERR_NOT_FOUND, "Resource not found.")
    return rec


def fk_or_404(collection, resource_id):
    """Validate a foreign-key reference exists, else ERR_NOT_FOUND."""
    if resource_id is None or resource_id not in collection:
        raise err(errors.ERR_NOT_FOUND, "Referenced resource not found.")
    return collection[resource_id]


def parse_dt(value):
    """Parse an ISO 8601 timestamp (accepting a trailing Z) to an aware UTC
    datetime. Raises ERR_INVALID_REQUEST on malformed input."""
    if not isinstance(value, str) or not value:
        raise err(errors.ERR_INVALID_REQUEST, "Timestamp must be an ISO 8601 string.")
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        raise err(errors.ERR_INVALID_REQUEST, "Malformed ISO 8601 timestamp.")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def half_open_overlap(a_start, a_end, b_start, b_end):
    """True if [a_start, a_end) overlaps [b_start, b_end) (half-open)."""
    return a_start < b_end and b_start < a_end


def windows_within_buffer(a_start, a_end, b_start, b_end, buffer_minutes):
    """True if interval B falls within buffer_minutes of interval A, treating
    A as a closed interval extended by the buffer on each side.

    The extended interval [a_start - buf, a_end + buf] is treated as closed,
    so B conflicts iff B's half-open span [b_start, b_end) intersects it.
    A point-touch at the extended boundary counts as a conflict (closed).
    """
    buf = timedelta(minutes=buffer_minutes)
    ext_start = a_start - buf
    ext_end = a_end + buf
    # B (half-open) intersects the closed extended interval when B starts at or
    # before ext_end AND B ends after ext_start.
    return b_start <= ext_end and b_end > ext_start
