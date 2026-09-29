"""In-memory store, logical clock and row bookkeeping.

Storage is process-local Python dicts keyed by id.  Nothing is persisted and
nothing is seeded: the store starts completely empty on every boot, exactly as
PRD §2.4 / §3 require (every row is created through the declared API surface).
"""

import itertools
import re
import threading
import uuid
from datetime import datetime, timezone, timedelta, date as _date

from flask import g

LOCK = threading.RLock()

COLLECTIONS = (
    "offerings",
    "share_classes",
    "investors",
    "broker_dealers",
    "selling_agreements",
    "subscriptions",
    "share_lots",
    "nav_records",
    "distribution_declarations",
    "repurchase_periods",
    "repurchase_requests",
    "liquidity_events",
    "stockholder_votes",
)

DB = {name: {} for name in COLLECTIONS}

# PRD §2.6 — "At boot the logical clock reads 2026-08-01T00:00:00Z."
BOOT_INSTANT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
CLOCK = {"now": BOOT_INSTANT}

_SEQ = itertools.count(1)


# --------------------------------------------------------------------------
# Timestamp helpers
# --------------------------------------------------------------------------

def wall_now():
    return datetime.now(timezone.utc)


def fmt_wall(dt):
    """PRD §2.4 — ISO 8601 UTC with three fractional digits."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def fmt_instant(dt):
    """Logical-clock instants (PRD §2.6: compared to the second)."""
    ms = dt.microsecond // 1000
    if ms:
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % ms
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def logical_now():
    return CLOCK["now"]


def logical_date():
    """PRD §2.6 — the calendar date in UTC of the logical clock's instant."""
    return CLOCK["now"].date()


def logical_date_str():
    return logical_date().isoformat()


_INSTANT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt](\d{2}):(\d{2}):(\d{2})(\.\d+)?([Zz]|[+-]\d{2}:?\d{2})?$"
)
_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_MONTH_RE = re.compile(r"^(\d{4})-(\d{2})$")


def parse_instant(value):
    """Parse an ISO 8601 instant.  Returns None when malformed."""
    if not isinstance(value, str):
        return None
    m = _INSTANT_RE.match(value.strip())
    if not m:
        return None
    frac = m.group(7) or ""
    micro = 0
    if frac:
        digits = (frac[1:] + "000000")[:6]
        micro = int(digits)
    tz = m.group(8)
    try:
        base = datetime(
            int(m.group(1)), int(m.group(2)), int(m.group(3)),
            int(m.group(4)), int(m.group(5)), int(m.group(6)),
            micro, tzinfo=timezone.utc,
        )
    except ValueError:
        return None
    if tz and tz not in ("Z", "z"):
        sign = 1 if tz[0] == "+" else -1
        body = tz[1:].replace(":", "")
        offs = timedelta(hours=int(body[:2]), minutes=int(body[2:4]))
        base = base - sign * offs
    return base


def parse_date(value):
    """Parse a YYYY-MM-DD calendar date.  Returns None when malformed."""
    if not isinstance(value, str) or not _DATE_RE.match(value.strip()):
        return None
    try:
        return _date.fromisoformat(value.strip())
    except ValueError:
        return None


def parse_month(value):
    """Parse a YYYY-MM month.  Returns (year, month) or None."""
    if not isinstance(value, str):
        return None
    m = _MONTH_RE.match(value.strip())
    if not m:
        return None
    year, month = int(m.group(1)), int(m.group(2))
    if month < 1 or month > 12:
        return None
    return year, month


# --------------------------------------------------------------------------
# Rows
# --------------------------------------------------------------------------

def new_row(collection, fields, common=True):
    row = dict(fields)
    row["_type"] = collection
    row["_seq"] = next(_SEQ)
    row["id"] = str(uuid.uuid4())
    stamp = fmt_wall(wall_now())
    row["created_at"] = stamp
    if common:
        row["updated_at"] = stamp
        row["version"] = 1
    DB[collection][row["id"]] = row
    return row


def _touched_set():
    if not hasattr(g, "_touched_rows"):
        g._touched_rows = set()
    return g._touched_rows


def touch(row):
    """PRD §2.4 — a mutated row refreshes updated_at and bumps version by
    exactly 1.  One request is one mutation, so a row touched several times
    inside the same request (direct write plus cascade plus derived-figure
    refresh) still advances its counter by exactly one."""
    if row is None or "version" not in row:
        return
    key = (row["_type"], row["id"])
    seen = _touched_set()
    if key in seen:
        return
    seen.add(key)
    row["version"] += 1
    row["updated_at"] = fmt_wall(wall_now())


def sort_key(row):
    """PRD §2.5 — ascending created_at, insertion order settling identical
    stamps.  No ordering anywhere consults an id."""
    return (row["created_at"], row["_seq"])


def by_created(rows):
    return sorted(rows, key=sort_key)


def all_rows(collection):
    return by_created(DB[collection].values())


def get(collection, row_id):
    if not isinstance(row_id, str):
        return None
    return DB[collection].get(row_id)
