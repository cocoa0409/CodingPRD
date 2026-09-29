"""In-memory data store and the logical UTC district clock.

PRD §2.4: nothing in this service reads wall-clock time. Before any client has
moved it, the logical clock reads exactly 2026-08-01T00:00:00Z.

The store starts completely empty on every boot; no entity is ever seeded.
"""

import uuid
from datetime import date, datetime, timezone

DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        self.schools = {}
        self.psychologists = {}
        self.referrals = {}
        self.evaluations = {}
        self.exclusions = {}
        self.instruments = {}
        self.orders = {}
        self.seats = {}
        self.sessions = {}
        self.meetings = {}
        self.breaches = {}
        self.clock = DEFAULT_CLOCK
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def now():
    """The current logical clock instant (UTC)."""
    return db.clock


def today():
    """The current logical clock UTC calendar date."""
    return db.clock.date()


def new_id():
    return str(uuid.uuid4())


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits and a trailing Z."""
    if dt is None:
        return None
    d = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        d.year, d.month, d.day, d.hour, d.minute, d.second, d.microsecond // 1000,
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
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_date(value):
    """Parse a strict YYYY-MM-DD calendar date. Returns None when unparseable."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if len(text) != 10 or text[4] != "-" or text[7] != "-":
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def date_str(d):
    return None if d is None else d.isoformat()


def sort_key(record):
    """Default list ordering: created_at ASC, insertion order as the tie-break.

    The logical clock does not advance on its own, so many records legitimately
    share a created_at value; the insertion sequence keeps ordering stable and
    deterministic without ever consulting the record's id.
    """
    return (record["created_at"], record["_seq"])


def base_record():
    stamp = iso(now())
    return {
        "id": new_id(),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
        "_seq": db.next_seq(),
    }


def touch(record):
    """Register a mutation: refresh updated_at and increment version by one."""
    record["updated_at"] = iso(now())
    record["version"] += 1
    return record
