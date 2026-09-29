"""In-memory data store, logical clock and instant helpers.

The store starts completely empty on every boot: no seeding, no preloading,
no persistence of any kind (no file, no sqlite, no /tmp cache).
"""
import re
import uuid
from datetime import datetime, timedelta, timezone

from flask import g

# PRD 2.5: fixed startup default of the logical clock. Never the host wall clock.
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

COLLECTIONS = (
    "disasters",
    "applicants",
    "facilities",
    "damage_sites",
    "projects",
    "cost_line_items",
    "force_account_resources",
    "contracts",
    "insurance_policies",
    "drawdowns",
    "progress_reports",
    "deobligations",
    "appeals",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.index = {}
        self.clock = DEFAULT_CLOCK
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


# ---------------------------------------------------------------------------
# instants
# ---------------------------------------------------------------------------

_DT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})"
    r"(?::(\d{2}))?(?:\.(\d{1,9}))?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)


def parse_instant(value):
    """Parse an ISO 8601 instant. Returns an aware UTC datetime or None."""
    if not isinstance(value, str):
        return None
    m = _DT_RE.match(value.strip())
    if not m:
        return None
    year, month, day, hour, minute = (int(m.group(i)) for i in range(1, 6))
    second = int(m.group(6) or 0)
    frac = m.group(7) or ""
    micro = int((frac + "000000")[:6]) if frac else 0
    offset = m.group(8)
    try:
        if offset in (None, "Z", "z"):
            tz = timezone.utc
        else:
            sign = 1 if offset[0] == "+" else -1
            body = offset[1:].replace(":", "")
            tz = timezone(sign * timedelta(hours=int(body[:2]), minutes=int(body[2:4])))
        dt = datetime(year, month, day, hour, minute, second, micro, tzinfo=tz)
    except ValueError:
        return None
    return dt.astimezone(timezone.utc)


def format_instant(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def now():
    """The logical clock as an aware datetime."""
    return db.clock


def now_iso():
    return format_instant(db.clock)


def dt_of(row, field):
    """Parsed datetime of a stored instant field (stored verbatim as supplied)."""
    value = row.get(field)
    if value is None:
        return None
    return parse_instant(value)


# ---------------------------------------------------------------------------
# rows / mutation bookkeeping
# ---------------------------------------------------------------------------


def begin_request():
    g.dirty = set()
    g.created = set()


def new_row(collection, fields):
    row_id = str(uuid.uuid4())
    row = {"id": row_id}
    row.update(fields)
    stamp = now_iso()
    row["created_at"] = stamp
    row["updated_at"] = stamp
    row["version"] = 1
    row["_seq"] = db.next_seq()
    getattr(db, collection)[row_id] = row
    db.index[row_id] = row
    g.created.add(row_id)
    return row


def setf(row, field, value):
    """Assign a field; mark the row mutated only when the value actually moves."""
    if row.get(field) != value:
        row[field] = value
        if row["id"] not in g.created:
            g.dirty.add(row["id"])
        return True
    return False


def touch(row):
    """Force a version/updated_at bump for a row the request explicitly mutates."""
    if row["id"] not in g.created:
        g.dirty.add(row["id"])


def commit():
    """Apply version + updated_at to every row mutated during this request."""
    stamp = now_iso()
    for row_id in g.dirty:
        row = db.index.get(row_id)
        if row is None:
            continue
        row["version"] = row["version"] + 1
        row["updated_at"] = stamp
    g.dirty = set()


def serialize(row):
    return dict((k, v) for k, v in row.items() if not k.startswith("_"))


def order_key(row):
    """Default list ordering: created_at ascending, creation sequence as tiebreak."""
    return (row["created_at"], row["_seq"])
