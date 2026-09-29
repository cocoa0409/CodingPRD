"""In-memory data store, logical clock and common-field helpers.

The store starts completely empty on every boot: nothing is seeded, preloaded
or hardcoded.  Every row is created through a declared endpoint.
"""

import re
import threading
import uuid
from datetime import datetime, timedelta, timezone

from flask import g

# --------------------------------------------------------------------------
# Stores.  One dict per entity, insertion-ordered, keyed by the row's UUID.
# --------------------------------------------------------------------------
licensees = {}
bonds = {}
terminals = {}
certificates = {}
rack_removals = {}
returns = {}
schedules = {}
schedule_lines = {}
cross_match_runs = {}
discrepancies = {}
refund_claims = {}
inspections = {}
audit_cases = {}
ledger_entries = {}

_lock = threading.RLock()

# The logical clock.  PRD section 2.5: before any call to
# POST /_clock/set_current_utc it reads exactly 2026-08-01T00:00:00Z, and the
# server never falls back to the host's real wall-clock time.
_CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0)
_clock = {"now": _CLOCK_DEFAULT}

_seq = {"n": 0}


def now():
    """The current logical instant as a naive UTC datetime."""
    return _clock["now"]


def set_clock(dt):
    _clock["now"] = dt


def next_seq():
    _seq["n"] += 1
    return _seq["n"]


def new_id():
    """PRD section 2.4: a UUID with no type prefix."""
    return str(uuid.uuid4())


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def iso_date(d):
    if d is None:
        return None
    return d.strftime("%Y-%m-%d")


_TS_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})(?::(\d{2}))?(\.\d+)?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$")


def parse_timestamp(value):
    """Parse an ISO 8601 instant into a naive UTC datetime, or return None."""
    if not isinstance(value, str):
        return None
    m = _TS_RE.match(value.strip())
    if not m:
        return None
    year, month, day, hour, minute = (int(m.group(i)) for i in range(1, 6))
    second = int(m.group(6) or 0)
    frac = m.group(7)
    micro = 0
    if frac:
        micro = int(round(float(frac) * 1000000))
    try:
        dt = datetime(year, month, day, hour, minute, second, micro)
    except ValueError:
        return None
    off = m.group(8)
    if off and off not in ("Z", "z"):
        sign = 1 if off[0] == "+" else -1
        body = off[1:].replace(":", "")
        dt = dt - sign * timedelta(hours=int(body[:2]), minutes=int(body[2:4]))
    return dt


def utcnow_real():
    return datetime.now(timezone.utc).replace(tzinfo=None)


# --------------------------------------------------------------------------
# Common fields (PRD section 2.4).
# --------------------------------------------------------------------------
def base_row(versioned=True):
    """Fresh common fields.

    Versioned rows carry id / created_at / updated_at / version, with version
    starting at 1.  RackRemoval, ScheduleLine and LedgerEntry are append-only
    and carry only id and created_at -- updated_at and version are absent
    entirely.
    """
    stamp = iso(now())
    row = {"id": new_id(), "created_at": stamp, "_seq": next_seq()}
    if versioned:
        row["updated_at"] = stamp
        row["version"] = 1
    return row


def touch(row):
    """Bump updated_at and version by exactly one for this mutation.

    A row mutated several times while serving one request advances its version
    by exactly one: PRD section 2.4 counts one increment per mutation of the
    row, and section 2.9 requires every row a cascade touches to be mutated in
    full.
    """
    if row is None or "version" not in row:
        return row
    seen = getattr(g, "_touched_rows", None)
    if seen is None:
        seen = set()
        try:
            g._touched_rows = seen
        except RuntimeError:
            pass
    key = id(row)
    if key in seen:
        return row
    seen.add(key)
    row["version"] += 1
    row["updated_at"] = iso(now())
    return row


def ordered(store):
    """Every row of a store in created_at ascending order.

    _seq breaks ties: the logical clock does not advance on its own, so rows
    created without moving it share a created_at to the millisecond.
    """
    return sorted(store.values(), key=lambda r: (r["created_at"], r["_seq"]))


def sort_rows(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


# --------------------------------------------------------------------------
# Calendar-month helpers.  Periods are 'YYYY-MM' strings throughout.
# --------------------------------------------------------------------------
def month_index(period_month):
    year, month = period_month.split("-")
    return int(year) * 12 + (int(month) - 1)


def month_from_index(index):
    return "%04d-%02d" % (index // 12, index % 12 + 1)


def month_start(period_month):
    year, month = period_month.split("-")
    return datetime(int(year), int(month), 1)


def month_end_date(period_month):
    """The last calendar date of the period, as a date object."""
    nxt = month_from_index(month_index(period_month) + 1)
    return (month_start(nxt) - timedelta(days=1)).date()


def period_due_at(period_month):
    """The 20th of the month following period_month at 23:59:59Z."""
    nxt = month_from_index(month_index(period_month) + 1)
    year, month = nxt.split("-")
    return datetime(int(year), int(month), 20, 23, 59, 59)


def period_is_closed(period_month):
    """A period is closed once the logical clock is at or past the first
    instant of the following month."""
    nxt = month_from_index(month_index(period_month) + 1)
    return now() >= month_start(nxt)


def date_in_month(d, period_month):
    return d.strftime("%Y-%m") == period_month
