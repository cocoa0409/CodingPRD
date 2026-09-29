"""In-memory data store, logical clock and common-field helpers.

The store starts empty on every boot. Nothing is seeded here.
"""

import itertools
import re
import uuid
from datetime import datetime, timedelta, timezone

from flask import g

DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

COLLECTIONS = (
    "elections",
    "contests",
    "ballot_batches",
    "custody_events",
    "audits",
    "audit_rounds",
    "audit_batches",
    "tally_teams",
    "manual_tallies",
    "discrepancies",
    "ballot_interpretations",
    "recounts",
    "corrective_actions",
    "observer_credentials",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock = DEFAULT_CLOCK
        self._seq = itertools.count(1)
        self.custody_seq = {}

    def next_seq(self):
        return next(self._seq)


db = Store()


# --------------------------------------------------------------------------
# time helpers
# --------------------------------------------------------------------------

_DT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,9}))?)?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def clock_now():
    return db.clock


def iso(dt):
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


def now_iso():
    return iso(db.clock)


def parse_dt(value):
    """Parse an ISO 8601 timestamp, returning an aware UTC datetime or None."""
    if not isinstance(value, str):
        return None
    m = _DT_RE.match(value.strip())
    if not m:
        return None
    year, month, day, hour, minute = (int(m.group(i)) for i in range(1, 6))
    second = int(m.group(6) or 0)
    frac = m.group(7) or ""
    micro = int((frac + "000000")[:6]) if frac else 0
    tz = m.group(8)
    try:
        base = datetime(year, month, day, hour, minute, second, micro, tzinfo=timezone.utc)
    except ValueError:
        return None
    if tz and tz not in ("Z", "z"):
        sign = 1 if tz[0] == "+" else -1
        body = tz[1:].replace(":", "")
        offset = timedelta(hours=int(body[:2]), minutes=int(body[2:4]))
        base = base - sign * offset
    return base


def parse_date(value):
    if not isinstance(value, str) or not _DATE_RE.match(value.strip()):
        return None
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def dt_of(value):
    """Parse a stored timestamp string (assumed well formed)."""
    if value is None:
        return None
    return parse_dt(value)


def plus_days(dt, days):
    return dt + timedelta(days=days)


# --------------------------------------------------------------------------
# row helpers
# --------------------------------------------------------------------------


def new_id():
    return str(uuid.uuid4())


def insert(collection, fields, common=True):
    row = {"id": new_id()}
    row.update(fields)
    if common:
        stamp = now_iso()
        row["created_at"] = stamp
        row["updated_at"] = stamp
        row["version"] = 1
    else:
        row["created_at"] = now_iso()
    row["_seq"] = db.next_seq()
    getattr(db, collection)[row["id"]] = row
    return row


def touch(row):
    """Refresh updated_at and bump version (at most one bump per request)."""
    if "version" not in row:
        return row
    touched = getattr(g, "_touched_rows", None)
    if touched is None:
        touched = set()
        g._touched_rows = touched
    row["updated_at"] = now_iso()
    key = id(row)
    if key not in touched:
        touched.add(key)
        row["version"] = row["version"] + 1
    return row


def set_fields(row, values):
    """Assign values, returning True when at least one field actually changed."""
    changed = False
    for key, value in values.items():
        if row.get(key) != value:
            row[key] = value
            changed = True
    return changed


def serialize(row):
    return {k: v for k, v in row.items() if not k.startswith("_")}


def sorted_rows(rows, keys=("created_at",)):
    def sort_key(row):
        out = []
        for k in keys:
            value = row.get(k)
            if value is None:
                value = ""
            out.append(value)
        out.append(row.get("_seq", 0))
        return tuple(out)

    return sorted(rows, key=sort_key)


def by_created(rows):
    return sorted_rows(rows, ("created_at",))
