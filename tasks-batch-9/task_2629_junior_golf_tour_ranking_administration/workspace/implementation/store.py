"""In-memory data store, logical clock and timestamp helpers.

The store starts completely empty on every boot: no seeded or preloaded rows.
"""
import re
import uuid
import itertools
from datetime import datetime, timezone, timedelta, date

from errors import ApiError

DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

COLLECTIONS = (
    "seasons",
    "members",
    "tournaments",
    "exemption_grants",
    "entries",
    "rounds",
    "rules_cases",
    "conduct_cases",
    "aid_applications",
    "coach_access_grants",
)


class DB(object):
    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock = DEFAULT_CLOCK
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


db = DB()


# --------------------------------------------------------------------------
# identifiers and timestamps
# --------------------------------------------------------------------------
def new_id():
    return str(uuid.uuid4())


def _as_utc(dt):
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso(dt):
    """An ISO 8601 UTC instant with a trailing Z (business-event precision).

    PRD 2.2 gives `created_at` / `updated_at` three fractional digits but
    describes the business-event stamps (`submitted_at`, `certified_at`,
    `decided_at`, `expires_at`, `tee_time`, ...) only as "ISO 8601 UTC
    instants", and it writes every such instant at second precision
    (`2026-08-01T00:00:00Z`). These are read from the logical clock, which is
    itself set from second-precision instants.
    """
    if dt is None:
        return None
    dt = _as_utc(dt)
    return "%04d-%02d-%02dT%02d:%02d:%02dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
    )


def iso_ms(dt):
    """ISO 8601 UTC with exactly three fractional digits and a trailing Z."""
    if dt is None:
        return None
    dt = _as_utc(dt)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def wall_now():
    return datetime.now(timezone.utc)


def wall_iso():
    """The row-audit stamp: three fractional digits, per PRD 2.2."""
    return iso_ms(wall_now())


def clock():
    """The process-wide logical clock (a timezone-aware UTC datetime)."""
    return db.clock


def clock_iso():
    return iso(db.clock)


def set_clock(dt):
    db.clock = dt


# --------------------------------------------------------------------------
# parsing
# --------------------------------------------------------------------------
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})(?::(\d{2}))?(\.\d+)?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)


def parse_date_str(value):
    """Parse a strict YYYY-MM-DD string. Returns a date or None on failure."""
    if not isinstance(value, str) or not _DATE_RE.match(value):
        return None
    try:
        return date(int(value[0:4]), int(value[5:7]), int(value[8:10]))
    except ValueError:
        return None


def parse_dt_str(value):
    """Parse an ISO 8601 timestamp. Returns an aware UTC datetime or None."""
    if not isinstance(value, str):
        return None
    m = _DT_RE.match(value.strip())
    if not m:
        return None
    year, month, day, hour, minute = (int(m.group(i)) for i in range(1, 6))
    second = int(m.group(6) or 0)
    frac = m.group(7)
    micro = 0
    if frac:
        micro = int(round(float(frac) * 1000000))
        if micro > 999999:
            micro = 999999
    offset = m.group(8)
    try:
        naive = datetime(year, month, day, hour, minute, second, micro)
    except ValueError:
        return None
    if offset in (None, "Z", "z"):
        return naive.replace(tzinfo=timezone.utc)
    sign = 1 if offset[0] == "+" else -1
    body = offset[1:].replace(":", "")
    delta = timedelta(hours=int(body[0:2]), minutes=int(body[2:4]))
    return (naive - sign * delta).replace(tzinfo=timezone.utc)


def dt_of(value):
    """Parse a stored ISO timestamp that is known to be well formed."""
    return parse_dt_str(value) if value else None


def date_of(value):
    return parse_date_str(value) if value else None


def day_start(date_string):
    """Midnight UTC of a stored YYYY-MM-DD date string."""
    d = parse_date_str(date_string)
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


# --------------------------------------------------------------------------
# rows
# --------------------------------------------------------------------------
def new_row():
    stamp = wall_iso()
    return {
        "id": new_id(),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
        "_seq": db.next_seq(),
    }


def touch(row):
    row["updated_at"] = wall_iso()
    row["version"] = row["version"] + 1
    return row


def public(row):
    if row is None:
        return None
    return {k: v for k, v in row.items() if not k.startswith("_")}


def ordered(rows):
    """Rows in default list order: created_at ascending, insertion order for ties."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def find(collection, row_id, error_id):
    if not isinstance(row_id, str) or not row_id:
        raise ApiError(error_id)
    row = getattr(db, collection).get(row_id)
    if row is None:
        raise ApiError(error_id)
    return row


def insert(collection, row):
    getattr(db, collection)[row["id"]] = row
    return row


def bump(row):
    """Refresh updated_at and increment version, at most once per request."""
    try:
        from flask import g, has_request_context
    except Exception:  # pragma: no cover
        return touch(row)
    if not has_request_context():
        return touch(row)
    seen = getattr(g, "_touched_rows", None)
    if seen is None:
        seen = set()
        g._touched_rows = seen
    key = row["id"]
    if key in seen:
        row["updated_at"] = wall_iso()
        return row
    seen.add(key)
    return touch(row)
