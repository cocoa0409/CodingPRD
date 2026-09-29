"""In-memory data store, logical clock and common-field bookkeeping.

The store starts completely empty on every boot: nothing is seeded, preloaded or
hardcoded. Every row is created through the declared API surface.
"""

import itertools
import uuid
from datetime import datetime, timedelta, timezone

from flask import g

TABLES = (
    "offices",
    "agencies",
    "actions",
    "screens",
    "statements",
    "alternatives",
    "scoping_periods",
    "issues",
    "analyses",
    "cumulative_actions",
    "consultations",
    "documents",
    "comments",
    "decisions",
    "mitigations",
    "objections",
    "record_entries",
)

db = {name: {} for name in TABLES}

_seq = itertools.count(1)

# PRD 2.7: before the clock is ever set it reads exactly 2026-08-01T00:00:00Z.
CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
_clock = {"now": CLOCK_DEFAULT}


def logical_now():
    return _clock["now"]


def set_logical_now(dt):
    _clock["now"] = dt


def iso(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def logical_iso():
    return iso(logical_now())


def real_iso():
    return iso(datetime.now(timezone.utc))


def parse_dt(value):
    """Parse an ISO 8601 instant. Returns None when unparseable."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def add_days(dt, days):
    """Whole-day arithmetic: exactly `days` 24-hour periods (PRD 2.7)."""
    return dt + timedelta(days=int(days))


def floor_days(start, end):
    """Floor of the exact elapsed days between two instants (PRD 2.7)."""
    delta = end - start
    return int(delta.total_seconds() // 86400)


def new_row(table, fields, common=True):
    row = {"id": str(uuid.uuid4())}
    stamp = real_iso()
    row["created_at"] = stamp
    if common:
        row["updated_at"] = stamp
        row["version"] = 1
    row.update(fields)
    row["_seq"] = next(_seq)
    db[table][row["id"]] = row
    return row


def touch(row):
    """Mutation bookkeeping: bump updated_at/version at most once per request."""
    if row is None or "version" not in row:
        return
    touched = getattr(g, "touched_rows", None)
    if touched is None:
        touched = set()
        g.touched_rows = touched
    if row["id"] in touched:
        return
    touched.add(row["id"])
    row["version"] = row["version"] + 1
    row["updated_at"] = real_iso()


def find(table, row_id):
    if not isinstance(row_id, str):
        return None
    return db[table].get(row_id)


def rows(table):
    """All rows of a table in created_at ascending (insertion) order."""
    return sorted(db[table].values(), key=lambda r: r["_seq"])


def where(table, **filters):
    out = []
    for row in rows(table):
        if all(row.get(k) == v for k, v in filters.items()):
            out.append(row)
    return out


def public(row):
    return {k: v for k, v in row.items() if not k.startswith("_")}


def public_list(items):
    return [public(r) for r in items]
