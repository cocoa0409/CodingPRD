"""In-memory data store.

The store starts completely empty on every boot: no seeding, no preloading,
no hardcoded entities. Every row is created through the declared API surface.
"""

import itertools
import re
import uuid
from datetime import datetime, timedelta, timezone

# PRD section 2.4 — the logical clock starts at this instant on every boot.
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})(?::(\d{2})(\.\d{1,9})?)?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)


def parse_dt(value):
    """Parse an ISO-8601 instant.  Returns an aware UTC datetime or None."""
    if not isinstance(value, str):
        return None
    m = _ISO_RE.match(value.strip())
    if not m:
        return None
    try:
        year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
        hour, minute = int(m.group(4)), int(m.group(5))
        second = int(m.group(6) or 0)
        frac = m.group(7)
        micro = 0
        if frac:
            micro = int(round(float(frac) * 1_000_000))
        tzs = m.group(8)
        if tzs in (None, "Z", "z"):
            tz = timezone.utc
        else:
            sign = 1 if tzs[0] == "+" else -1
            body = tzs[1:].replace(":", "")
            tz = timezone(sign * timedelta(hours=int(body[:2]), minutes=int(body[2:4])))
        dt = datetime(year, month, day, hour, minute, second, micro, tzinfo=tz)
    except ValueError:
        return None
    return dt.astimezone(timezone.utc)


def format_dt(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03dZ" % (dt.microsecond // 1000))


def iso_now():
    """Wall-clock timestamp for created_at / updated_at, 3 fractional digits."""
    return format_dt(datetime.now(timezone.utc))


class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        self.conferences = {}
        self.categories = {}
        self.authors = {}
        self.abstracts = {}
        self.members = {}
        self.declarations = {}
        self.reviews = {}
        self.cases = {}
        self.sessions = {}
        self.slots = {}
        self.accreditations = {}
        self.disclosures = {}
        self.change_requests = {}
        self.clock_raw = DEFAULT_CLOCK
        self.clock_dt = parse_dt(DEFAULT_CLOCK)
        self._counter = itertools.count(1)

    # ---- logical clock -------------------------------------------------
    def set_clock(self, raw):
        self.clock_dt = parse_dt(raw)
        self.clock_raw = raw

    def now(self):
        """Logical clock instant (aware datetime)."""
        return self.clock_dt

    def now_raw(self):
        return self.clock_raw

    def next_seq(self):
        return next(self._counter)


db = Store()


def new_row(fields):
    ts = iso_now()
    row = {
        "id": str(uuid.uuid4()),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }
    row.update(fields)
    return row


def touch(row):
    """Register a mutation: refresh updated_at and advance version by one."""
    row["updated_at"] = iso_now()
    row["version"] = row["version"] + 1
    return row


def sort_key(row):
    return (row["created_at"], row["_seq"])


def by_created_at(rows):
    return sorted(rows, key=sort_key)
