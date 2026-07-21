"""In-memory data store and the platform logical clock.

The store starts completely empty on every boot. Nothing is seeded.
"""

import itertools
import uuid
from datetime import datetime, timedelta, timezone

DEFAULT_LOGICAL_CLOCK_UTC = datetime(2026, 7, 1, 0, 0, 0, tzinfo=timezone.utc)

COLLECTIONS = (
    "events",
    "ticket_types",
    "registrations",
    "tracks",
    "sessions",
    "speakers",
    "session_speakers",
    "broadcasts",
    "recordings",
    "sponsors",
    "booths",
    "leads",
    "match_requests",
    "settlements",
)


class Store(object):
    def __init__(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock = DEFAULT_LOGICAL_CLOCK_UTC
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)

    def now(self):
        return self.clock

    def now_iso(self):
        return fmt_dt(self.clock)


S = Store()


def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional-second digits."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def parse_dt(value):
    """Parse an ISO 8601 instant. Returns None when unparseable."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def dt_of(row, field):
    return parse_dt(row.get(field))


def new_row(fields):
    now = S.now_iso()
    row = {
        "id": str(uuid.uuid4()),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": S.next_seq(),
    }
    row.update(fields)
    return row


def touch(row):
    """Record a mutation: bump updated_at and version."""
    row["updated_at"] = S.now_iso()
    row["version"] = int(row.get("version", 1)) + 1
    return row


def serialize(row):
    if row is None:
        return None
    return {k: v for k, v in row.items() if not k.startswith("_")}


def sort_rows(rows):
    """Default ordering: created_at ascending, insertion order as tie-break."""
    return sorted(rows, key=lambda r: (r.get("created_at") or "", r.get("_seq", 0)))


def minutes(n):
    return timedelta(minutes=n)
