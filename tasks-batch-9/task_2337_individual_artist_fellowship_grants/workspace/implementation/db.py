"""In-memory store.

Every collection starts EMPTY on boot.  Nothing is seeded, preloaded or
hardcoded — tests construct all state through the declared API surface.
"""

import itertools
import uuid
from datetime import datetime, timedelta, timezone

from flask import g

# ---------------------------------------------------------------- collections

TABLES = (
    "cycles",
    "disciplines",
    "artists",
    "applications",
    "work_samples",
    "panels",
    "panelists",
    "conflicts",
    "reviews",
    "slots",
    "awards",
    "installments",
    "final_reports",
    "appeals",
)

store = {name: {} for name in TABLES}

_seq = itertools.count(1)

# ------------------------------------------------------------- logical clock

CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
_clock = {"now": CLOCK_DEFAULT}


def now():
    """The logical clock — every temporal rule reads this, never wall time."""
    return _clock["now"]


def set_now(value):
    _clock["now"] = value


# ------------------------------------------------------------------ time i/o


def iso3(dt):
    """ISO 8601 UTC with exactly three fractional-second digits."""
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


def parse_dt(raw):
    """Parse an ISO 8601 instant (or bare date) into an aware UTC datetime."""
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise ValueError("not a string")
    text = raw.strip()
    if not text:
        raise ValueError("empty")
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    value = datetime.fromisoformat(text)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def dt_of(row, field):
    raw = row.get(field)
    if raw is None:
        return None
    return parse_dt(raw)


def date_of(row, field):
    value = dt_of(row, field)
    return None if value is None else value.date()


def plus_days(value, days):
    return value + timedelta(days=days)


def wall_now():
    return datetime.now(timezone.utc)


# ------------------------------------------------------------------ row mgmt


def insert(table, fields):
    row_id = str(uuid.uuid4())
    stamp = iso3(wall_now())
    row = {"id": row_id, "created_at": stamp, "updated_at": stamp, "version": 1}
    row.update(fields)
    row["_seq"] = next(_seq)
    store[table][row_id] = row
    # A brand-new row is already "touched" this request: version stays at 1 even
    # when the derived-field pass writes computed values into it straight away.
    _touched_set().add(row_id)
    return row


def _touched_set():
    try:
        touched = g._touched
    except (AttributeError, RuntimeError):
        touched = None
    if touched is None:
        touched = set()
        try:
            g._touched = touched
        except RuntimeError:
            pass
    return touched


def mark(row):
    """Record a mutation: refresh updated_at and bump version.

    Idempotent within a single request so that one accepted operation moves a
    row's version by exactly one, however many cascade steps touched it.
    """
    if row is None:
        return row
    touched = _touched_set()
    if row["id"] in touched:
        return row
    touched.add(row["id"])
    row["updated_at"] = iso3(wall_now())
    row["version"] = row.get("version", 0) + 1
    return row


def public(row):
    """Serialize a row: every field except internal bookkeeping."""
    return {k: v for k, v in row.items() if not k.startswith("_")}


def get(table, row_id):
    if not isinstance(row_id, str):
        return None
    return store[table].get(row_id)


def rows(table, predicate=None):
    out = [r for r in store[table].values() if predicate is None or predicate(r)]
    out.sort(key=lambda r: r["_seq"])
    return out
