"""In-memory data store and logical-clock utilities.

The store is a set of plain Python dicts keyed by id. It starts completely empty
on every boot: nothing is seeded, preloaded or hardcoded here. Every entity the
API exposes is created by an explicit client request.
"""

import itertools
import re
import uuid
from datetime import datetime, timedelta, timezone

# PRD 2.4: before any clock call the logical clock reads exactly this instant and
# never falls back to real wall-clock time.
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

_ISO_RE = re.compile(
    r"^(?P<y>\d{4})-(?P<mo>\d{2})-(?P<d>\d{2})"
    r"[Tt ](?P<h>\d{2}):(?P<mi>\d{2})(?::(?P<s>\d{2}))?"
    r"(?:\.(?P<frac>\d{1,9}))?"
    r"(?P<tz>[Zz]|[+-]\d{2}:?\d{2})?$"
)


def parse_iso(value):
    """Parse an ISO-8601 instant into an aware UTC datetime, or None if invalid."""
    if not isinstance(value, str):
        return None
    m = _ISO_RE.match(value.strip())
    if not m:
        return None
    try:
        micro = 0
        if m.group("frac"):
            frac = (m.group("frac") + "000000")[:6]
            micro = int(frac)
        dt = datetime(
            int(m.group("y")),
            int(m.group("mo")),
            int(m.group("d")),
            int(m.group("h")),
            int(m.group("mi")),
            int(m.group("s") or 0),
            micro,
            tzinfo=timezone.utc,
        )
    except ValueError:
        return None
    tz = m.group("tz")
    if tz and tz not in ("Z", "z"):
        sign = 1 if tz[0] == "+" else -1
        body = tz[1:].replace(":", "")
        offset = timedelta(hours=int(body[:2]), minutes=int(body[2:4]))
        dt = dt - sign * offset
    return dt


def format_iso(dt):
    """Render an aware datetime as an ISO-8601 UTC instant with 3 fractional digits."""
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


def format_clock(dt):
    """Render the logical clock value the way PRD 2.4 writes it.

    The document quotes the clock as reading exactly ``2026-08-01T00:00:00Z``, so a
    whole-second instant carries no fractional part; sub-second precision is kept
    to three digits when the operator supplies it.
    """
    dt = dt.astimezone(timezone.utc)
    head = "%04d-%02d-%02dT%02d:%02d:%02d" % (
        dt.year,
        dt.month,
        dt.day,
        dt.hour,
        dt.minute,
        dt.second,
    )
    if dt.microsecond:
        return "%s.%03dZ" % (head, dt.microsecond // 1000)
    return head + "Z"


class Store(object):
    """All collections live here. Every dict starts empty."""

    COLLECTIONS = (
        "venues",
        "zones",
        "events",
        "assessments",
        "plans",
        "posts",
        "subcontractors",
        "guards",
        "assignments",
        "lanes",
        "readings",
        "incidents",
        "reviews",
    )

    def __init__(self):
        self.reset()

    def reset(self):
        for name in self.COLLECTIONS:
            setattr(self, name, {})
        self._seq = itertools.count(1)
        self.clock = parse_iso(DEFAULT_CLOCK_ISO)

    def next_seq(self):
        return next(self._seq)


db = Store()


def now():
    """The logical clock."""
    return db.clock


def now_iso():
    return format_iso(db.clock)


def clock_iso():
    """The logical clock value, for fields PRD 2.4 stamps with it."""
    return format_clock(db.clock)


def new_id():
    return str(uuid.uuid4())


def make_record(fields, versioned=True):
    rec = dict(fields)
    rec["id"] = new_id()
    rec["created_at"] = now_iso()
    rec["_seq"] = db.next_seq()
    if versioned:
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1
    return rec


def touch(rec):
    """Refresh updated_at and increment version (PRD 2.4 / 2.8)."""
    if "version" in rec:
        rec["version"] = rec["version"] + 1
    if "updated_at" in rec:
        rec["updated_at"] = now_iso()
    return rec


def sort_key(rec):
    """Ascending created_at with a stable insertion-order tie-break."""
    return (rec.get("created_at") or "", rec.get("_seq") or 0)


def sorted_records(records):
    return sorted(records, key=sort_key)


def apply_fields(rec, changes):
    """Assign changes; return True when at least one stored value actually moved."""
    changed = False
    for key, value in changes.items():
        if rec.get(key, "\x00missing") != value:
            rec[key] = value
            changed = True
    return changed
