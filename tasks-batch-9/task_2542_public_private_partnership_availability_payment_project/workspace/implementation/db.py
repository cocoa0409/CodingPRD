"""In-memory store, logical clock and row bookkeeping.

The store is EMPTY on every boot: nothing is seeded, preloaded or hardcoded.
"""

import copy
import re
import uuid
from datetime import datetime, timedelta, timezone

from flask import g

from errors import ApiError

CLOCK_DEFAULT = "2026-08-01T00:00:00Z"

TABLE_NAMES = (
    "concessionaires",
    "concessions",
    "milestones",
    "periods",
    "reports",
    "events",
    "disputes",
    "claims",
    "reserve_txns",
    "refis",
    "enforcements",
)

_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})"
    r"(?:[Tt ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,9}))?)?"
    r"(Z|z|[+-]\d{2}:?\d{2})?)?$"
)


def parse_instant(value):
    """Parse an ISO-8601 date or datetime into an aware UTC datetime.

    Returns None when the value is not a parseable instant.
    """
    if not isinstance(value, str):
        return None
    m = _ISO_RE.match(value.strip())
    if not m:
        return None
    year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
    hour = int(m.group(4) or 0)
    minute = int(m.group(5) or 0)
    second = int(m.group(6) or 0)
    frac = m.group(7) or ""
    micro = int((frac + "000000")[:6]) if frac else 0
    tz = m.group(8)
    try:
        dt = datetime(year, month, day, hour, minute, second, micro, tzinfo=timezone.utc)
    except ValueError:
        return None
    if tz and tz not in ("Z", "z"):
        sign = 1 if tz[0] == "+" else -1
        body = tz[1:].replace(":", "")
        offs = timedelta(hours=int(body[:2]), minutes=int(body[2:4]))
        dt = dt - sign * offs
    return dt


def format_instant(dt):
    """ISO 8601 UTC with exactly three fractional digits and a Z suffix."""
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, dt.microsecond // 1000,
    )


def format_date(dt):
    """Calendar date in ISO 8601 date form, with no time component."""
    return "%04d-%02d-%02d" % (dt.year, dt.month, dt.day)


def is_date_only(value):
    """True when a raw ISO 8601 string carries a date and no time component."""
    if not isinstance(value, str):
        return False
    text = value.strip()
    return len(text) == 10 and "T" not in text and "t" not in text and " " not in text


def whole_days(a, b):
    """Whole calendar days from instant a to instant b (may be negative)."""
    return (b.date() - a.date()).days


class Store(object):
    def __init__(self):
        self.tables = {}
        self.clock = parse_instant(CLOCK_DEFAULT)
        self._counter = 0
        for name in TABLE_NAMES:
            self.tables[name] = {}

    # ---- clock -------------------------------------------------------
    def now(self):
        return self.clock

    def now_str(self):
        return format_instant(self.clock)

    def set_clock(self, dt):
        self.clock = dt

    # ---- rows --------------------------------------------------------
    def next_seq(self):
        self._counter += 1
        return self._counter

    def table(self, name):
        return self.tables[name]

    def all(self, name):
        """Rows of a table in insertion order (== created_at ascending)."""
        return sorted(self.tables[name].values(), key=lambda r: (r["created_at"], r["_seq"]))

    def snapshot(self):
        return (copy.deepcopy(self.tables), self.clock, self._counter)

    def restore(self, snap):
        self.tables, self.clock, self._counter = snap[0], snap[1], snap[2]


db = Store()


def new_id():
    return str(uuid.uuid4())


def insert(table, row, versioned=True):
    row["id"] = new_id()
    row["created_at"] = db.now_str()
    if versioned:
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    row["_seq"] = db.next_seq()
    db.tables[table][row["id"]] = row
    return row


def touch(row):
    """Bump updated_at/version at most once per request for a given row."""
    if "version" not in row:
        return row
    touched = getattr(g, "_touched", None)
    if touched is None:
        touched = set()
        g._touched = touched
    if row["id"] in touched:
        return row
    touched.add(row["id"])
    row["version"] += 1
    row["updated_at"] = db.now_str()
    return row


def setf(row, field, value):
    """Assign a field, bumping the row's version only when the value changes."""
    if row.get(field) != value:
        row[field] = value
        touch(row)
    return row


def public(row):
    return {k: v for k, v in row.items() if not k.startswith("_")}
