"""In-memory data store, logical clock and row bookkeeping.

The store starts completely EMPTY on every boot: nothing is seeded, preloaded or
hardcoded.  Every entity a caller needs is created through the declared API.
"""

import itertools
import uuid
from datetime import datetime, timezone

from flask import g

# --- logical clock (PRD 2.4) -------------------------------------------------
# Before any call the logical clock reads exactly 2026-08-01T00:00:00Z.  The
# server never falls back to real wall-clock time for time-sensitive figures.
CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

# --- entity tables ----------------------------------------------------------
clients = {}
staff_members = {}
engagements = {}
phases = {}
assignments = {}
availability_exceptions = {}
time_entries = {}
restrictions = {}
review_windows = {}
reschedule_plans = {}
waivers = {}

_state = {"clock": CLOCK_DEFAULT}
_seq = itertools.count(1)


def current_utc():
    return _state["clock"]


def current_date():
    return _state["clock"].date()


def set_clock(value):
    _state["clock"] = value


def iso_ts(moment=None):
    """ISO 8601 UTC timestamp with exactly three fractional digits (PRD 2.7)."""
    moment = moment or datetime.now(timezone.utc)
    return "%s.%03dZ" % (
        moment.strftime("%Y-%m-%dT%H:%M:%S"),
        moment.microsecond // 1000,
    )


def next_seq():
    return next(_seq)


def new_row(versioned=True):
    """Mint the common system-managed properties of PRD 2.7.

    ``versioned`` is False for the two append-only record types (availability
    exceptions and time entries) which carry only ``id`` and ``created_at``.
    """
    ts = iso_ts()
    row = {"id": str(uuid.uuid4()), "created_at": ts, "_seq": next_seq()}
    if versioned:
        row["updated_at"] = ts
        row["version"] = 1
    g.created.add(row["id"])
    return row


def mark(row):
    """Flag a row as mutated by the current request.

    Each row mutated during one request receives exactly one ``version``
    increment and one ``updated_at`` refresh (PRD 2.7 / 2.8).  Rows created by
    the same request keep version 1 and created_at == updated_at.
    """
    if row is None:
        return
    if row.get("id") in g.created:
        return
    g.marks[id(row)] = row


def commit():
    """Apply the pending updated_at / version bumps.  Called on success only."""
    ts = iso_ts()
    for row in g.marks.values():
        row["updated_at"] = ts
        if "version" in row:
            row["version"] = row["version"] + 1
    g.marks = {}


def by_seq(rows):
    return sorted(rows, key=lambda r: r["_seq"])
