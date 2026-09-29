"""In-memory data store, logical clock and shared record helpers.

The store starts completely empty on every boot: nothing is seeded, preloaded
or hardcoded here.  Every entity is created through the declared API surface.
"""

import uuid
from datetime import datetime, timedelta, timezone

# PRD 2.4: before the clock is ever set it reads exactly 2026-08-01T00:00:00Z.
CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store(object):
    def __init__(self):
        self.programs = {}
        self.jurisdictions = {}
        self.vendors = {}
        self.contracts = {}
        self.policies = {}
        self.notices = {}
        self.assets = {}
        self.subjects = {}
        self.consents = {}
        self.accommodations = {}
        self.incidents = {}
        self.assessments = {}
        self.clock = CLOCK_DEFAULT
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def now():
    """The logical UTC clock."""
    return db.clock


def new_id():
    return str(uuid.uuid4())


def new_record():
    ts = db.clock
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }


def touch(rec):
    """A real mutation: refresh updated_at and increment version by exactly 1."""
    rec["updated_at"] = db.clock
    rec["version"] += 1


def ordered(rows):
    """Default ordering: created_at ascending (stable by insertion sequence)."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def add_days(instant, days):
    if instant is None:
        return None
    return instant + timedelta(days=int(days))


def parse_iso(value):
    """Parse an ISO 8601 instant; returns None when unparseable."""
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


def fmt_iso(instant):
    """ISO 8601 UTC with exactly three fractional second digits."""
    if instant is None:
        return None
    inst = instant.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        inst.year,
        inst.month,
        inst.day,
        inst.hour,
        inst.minute,
        inst.second,
        inst.microsecond // 1000,
    )
