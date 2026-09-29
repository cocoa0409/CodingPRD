"""In-memory data store and the logical clock (§2.5).

The store is created empty at import time and is NEVER seeded with entity data.
"""

import itertools
import uuid
from datetime import datetime, timedelta, timezone

# Before any caller has set it, the logical clock reads exactly this instant.
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store(object):
    def __init__(self):
        self.rights_holders = {}
        self.works = {}
        self.periods = {}
        self.batches = {}
        self.usage_lines = {}
        self.registrations = {}
        self.pools = {}
        self.statements = {}
        self.statement_lines = {}
        self.engagements = {}
        self.rate_schedules = {}
        self.current_utc = DEFAULT_CLOCK
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


db = Store()


def new_id():
    return str(uuid.uuid4())


def now():
    """The current instant, read from the logical clock only."""
    return db.current_utc


def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    return "%s.%03dZ" % (dt.strftime("%Y-%m-%dT%H:%M:%S"), dt.microsecond // 1000)


def parse_dt(value):
    """Parse an ISO 8601 instant; returns None when unparseable."""
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


def parse_date(value):
    """Parse a YYYY-MM-DD calendar date; returns None when unparseable."""
    if not isinstance(value, str) or len(value) != 10:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def date_plus_days(date_str, days):
    base = parse_date(date_str)
    if base is None:
        return None
    return base + timedelta(days=days)


def stamp_new(record, versioned=True):
    """Attach the common fields (§2.4) to a brand new record."""
    ts = fmt_dt(now())
    record["id"] = new_id()
    record["created_at"] = ts
    record["_created_dt"] = now()
    record["_seq"] = db.next_seq()
    if versioned:
        record["updated_at"] = ts
        record["version"] = 1
    return record


def touch(record):
    """Register a mutation: refresh updated_at and increment version."""
    record["updated_at"] = fmt_dt(now())
    record["version"] = record.get("version", 1) + 1
    return record


def by_created(records):
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
