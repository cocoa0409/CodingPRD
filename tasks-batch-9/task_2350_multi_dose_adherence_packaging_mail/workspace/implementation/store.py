"""Row lifecycle helpers: creation, version bumping, ordering, serialization.

`version` starts at 1 and rises by exactly 1 per mutated row per request,
including mutations reached through a cascade (PRD 2.5 / 2.8).  A request
therefore collects the rows it mutated and bumps each of them once, at commit.
"""

from datetime import date, datetime, timedelta, timezone

from flask import g

import clock
import db


def create(table, fields, versioned=True):
    row = {"id": db.new_id()}
    row.update(fields)
    stamp = clock.now_iso()
    row["created_at"] = stamp
    if versioned:
        row["updated_at"] = stamp
        row["version"] = 1
    table[row["id"]] = row
    return row


def _pending():
    if not hasattr(g, "_touched_rows"):
        g._touched_rows = []
    return g._touched_rows


def touch(row):
    """Mark a row as mutated by this request (idempotent)."""
    pending = _pending()
    for existing in pending:
        if existing is row:
            return row
    pending.append(row)
    return row


def commit():
    stamp = clock.now_iso()
    for row in _pending():
        row["updated_at"] = stamp
        if "version" in row:
            row["version"] += 1
    g._touched_rows = []


def sort_key(row):
    """Ascending created_at, ascending id as the tie-break (PRD 2.3)."""
    return (row["created_at"], row["id"])


def ordered(rows):
    return sorted(rows, key=sort_key)


def serialize(row):
    return {k: v for k, v in row.items() if not k.startswith("_")}


def serialize_many(rows):
    return [serialize(r) for r in rows]


# ---------------------------------------------------------------- date helpers

def parse_date(value):
    return datetime.strptime(value, "%Y-%m-%d").date()


def fmt_date(value):
    return value.isoformat()


def d(value):
    """Stored ISO date string -> date (None-safe)."""
    return None if value is None else parse_date(value)


def ts(value):
    """Stored ISO instant string -> aware datetime (None-safe)."""
    if value is None:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def add_days(value, days):
    return value + timedelta(days=days)


def day_diff(later, earlier):
    """Whole days from `earlier` (inclusive) to `later` (exclusive)."""
    return (later - earlier).days


__all__ = [
    "create",
    "touch",
    "commit",
    "sort_key",
    "ordered",
    "serialize",
    "serialize_many",
    "parse_date",
    "fmt_date",
    "d",
    "ts",
    "add_days",
    "day_diff",
    "date",
]
