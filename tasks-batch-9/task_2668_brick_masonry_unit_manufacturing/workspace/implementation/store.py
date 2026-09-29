"""In-memory data store, logical clock, id minting and audit-column helpers.

The store starts EMPTY on every boot: nothing is seeded, preloaded or
hardcoded. Every entity is built by the caller through the declared API.
"""

import itertools
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from flask import g

# PRD 2.4: the logical clock's value at server startup is exactly this instant.
CLOCK_START = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

COLLECTIONS = (
    "plants",
    "clay_pits",
    "formulations",
    "kilns",
    "kiln_cars",
    "production_runs",
    "kiln_runs",
    "fired_lots",
    "orders",
    "blends",
    "blend_components",
    "sample_panels",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock = CLOCK_START
        self._seq = itertools.count(1)


db = Store()


# --------------------------------------------------------------------------
# clock / formatting
# --------------------------------------------------------------------------
def clock():
    return db.clock


def set_clock(dt):
    db.clock = dt


def fmt_dt(dt):
    if dt is None:
        return None
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


def now_str():
    return fmt_dt(db.clock)


def fmt_clock(dt):
    """Render a clock-derived business instant.

    PRD 2.4 pins the clock's own rendering ("exactly 2026-08-01T00:00:00Z") and
    PRD 3.5 pins a clock-derived stamp ("promises 15 days out, at
    2026-08-16T00:00:00Z"), i.e. second precision with no fractional part unless
    the clock itself carries one. The three-fractional-digit rule of PRD 2.4
    applies to `created_at` and `updated_at`, which keep using fmt_dt.
    """
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    stamp = "%04d-%02d-%02dT%02d:%02d:%02d" % (
        dt.year,
        dt.month,
        dt.day,
        dt.hour,
        dt.minute,
        dt.second,
    )
    if dt.microsecond:
        stamp += ".%03d" % (dt.microsecond // 1000)
    return stamp + "Z"


def clock_str():
    return fmt_clock(db.clock)


def add_days(dt, days):
    return dt + timedelta(days=int(days))


def parse_dt(value):
    """Parse an ISO 8601 instant. Returns None when unparseable."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


# --------------------------------------------------------------------------
# identity / audit columns
# --------------------------------------------------------------------------
def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(db._seq)


def new_row(**fields):
    """Mint a row with the four common properties of PRD 2.4."""
    row = {"id": new_id()}
    row.update(fields)
    row["created_at"] = now_str()
    row["updated_at"] = now_str()
    row["version"] = 1
    row["_seq"] = next_seq()
    return row


def touch(row):
    """Refresh updated_at and increment version by exactly 1 (once per request).

    PRD 2.10: every row a cascade touches has its updated_at refreshed and its
    version incremented by 1, exactly as if it had been mutated directly.
    """
    touched = getattr(g, "_touched_rows", None)
    if touched is None:
        touched = set()
        g._touched_rows = touched
    row["updated_at"] = now_str()
    if id(row) in touched:
        return row
    touched.add(id(row))
    row["version"] = int(row["version"]) + 1
    return row


def sort_rows(rows):
    """List results are sorted by created_at ascending (stable by insertion)."""
    return sorted(rows, key=lambda r: (r.get("created_at") or "", r.get("_seq") or 0))


def values(collection):
    return sort_rows(list(collection.values()))


# --------------------------------------------------------------------------
# public projection
# --------------------------------------------------------------------------
def public(row):
    if row is None:
        return None
    out = {}
    for key, value in row.items():
        if key.startswith("_"):
            continue
        out[key] = _conv(value)
    return out


def _conv(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {k: _conv(v) for k, v in value.items() if not k.startswith("_")}
    if isinstance(value, (list, tuple)):
        return [_conv(v) for v in value]
    return value
