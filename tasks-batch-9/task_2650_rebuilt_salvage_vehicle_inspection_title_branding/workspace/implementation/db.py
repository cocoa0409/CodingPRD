"""In-memory store, server-held logical clock and row helpers.

Storage is process memory only: plain dicts keyed by id.  The store is empty on
every boot; nothing is ever seeded.
"""

import threading
import uuid
from datetime import datetime, timedelta, timezone

# The logical clock starts here on every boot and only ever moves because a
# client asks it to.  Wall-clock time is never consulted for domain instants.
INITIAL_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

COLLECTIONS = (
    "vehicles",
    "rebuilders",
    "inspectors",
    "stations",
    "damage_reports",
    "titles",
    "applications",
    "parts_documents",
    "inspections",
    "findings",
    "appeals",
    "referrals",
    "recognitions",
    "transfers",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.clock = INITIAL_CLOCK
        self._seq = 0
        for name in COLLECTIONS:
            setattr(self, name, {})

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()
request_lock = threading.RLock()


def new_id():
    return str(uuid.uuid4())


def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits and a trailing Z."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year,
        dt.month,
        dt.day,
        dt.hour,
        dt.minute,
        dt.second,
        dt.microsecond // 1000,
    )


def parse_dt(value):
    """Parse an ISO 8601 instant; return an aware UTC datetime or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def now():
    return db.clock


def now_iso():
    return fmt_dt(db.clock)


def days(count):
    return timedelta(days=count)


def minutes(count):
    return timedelta(minutes=count)


def new_row(with_common=True):
    """A fresh row carrying the system fields every entity publishes."""
    row = {"id": new_id(), "created_at": now_iso(), "_seq": db.next_seq(), "_created": now()}
    if with_common:
        row["updated_at"] = now_iso()
        row["version"] = 1
    return row


def touch(row):
    """Refresh updated_at and bump the concurrency counter of a mutated row."""
    if row is None:
        return
    if "version" in row:
        row["updated_at"] = now_iso()
        row["version"] = row["version"] + 1


def ordered(rows):
    """Every collection is ordered by created_at ascending (stable)."""
    return sorted(rows, key=lambda r: (r["_created"], r["_seq"]))
