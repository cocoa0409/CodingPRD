"""In-memory store, logical clock and row bookkeeping helpers.

Storage is process-local Python dicts only: no SQLite, no files, no external
persistence, and nothing is seeded at import time. Every row is created by a
client through a declared endpoint.
"""

import itertools
import uuid
from datetime import datetime, timedelta, timezone

# The logical clock reads exactly this instant until a SystemAdmin moves it and
# never falls back to the host's wall-clock time (PRD Section 2.4).
CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_COLLECTIONS = (
    "journals",
    "editors",
    "authors",
    "reviewers",
    "manuscripts",
    "screenings",
    "assignments",
    "invitations",
    "reviews",
    "decisions",
    "appeals",
    "ethics_cases",
    "production_jobs",
    "invoices",
)


class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        for name in _COLLECTIONS:
            setattr(self, name, {})
        self.clock = CLOCK_EPOCH
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


store = Store()


# --------------------------------------------------------------------------
# identity and timestamps
# --------------------------------------------------------------------------
def new_id():
    """A UUID with no type prefix and no domain-derived structure."""
    return str(uuid.uuid4())


def fmt_ts(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_ts(text):
    """Parse an ISO-8601 UTC instant; returns None for a null/blank value."""
    if text is None:
        return None
    if isinstance(text, datetime):
        dt = text
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    s = str(text).strip()
    if not s:
        return None
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def now():
    """The logical clock instant every clock-derived field reads."""
    return store.clock


def now_iso():
    return fmt_ts(store.clock)


def add_days(dt, days):
    return dt + timedelta(days=days)


# --------------------------------------------------------------------------
# row bookkeeping
# --------------------------------------------------------------------------
def stamp_new(row, versioned=True):
    """Attach id, created_at and (for mutable rows) updated_at / version."""
    row["id"] = new_id()
    ts = now_iso()
    row["created_at"] = ts
    if versioned:
        row["updated_at"] = ts
        row["version"] = 1
    row["_seq"] = store.next_seq()
    return row


def touch(row):
    """Refresh updated_at and advance version by exactly 1 for this request.

    Section 2.9 requires every row mutated by a request - including rows
    mutated as a side effect of an operation addressed elsewhere - to advance
    its version by 1. A row touched twice inside one request still advances by
    exactly 1, so a cascade that rewrites the same row twice is one mutation.
    """
    if row is None:
        return row
    try:
        from flask import g, has_request_context

        if has_request_context():
            seen = getattr(g, "_touched_rows", None)
            if seen is None:
                seen = set()
                g._touched_rows = seen
            key = id(row)
            if key in seen:
                row["updated_at"] = now_iso()
                return row
            seen.add(key)
    except RuntimeError:  # pragma: no cover - defensive
        pass
    if "version" in row:
        row["version"] = int(row["version"]) + 1
    if "updated_at" in row:
        row["updated_at"] = now_iso()
    return row


def ordered(rows):
    """created_at ascending, insertion sequence as the deterministic tiebreak."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def public(row):
    """Strip internal bookkeeping keys from a stored row."""
    if row is None:
        return None
    return {k: v for k, v in row.items() if not k.startswith("_")}
