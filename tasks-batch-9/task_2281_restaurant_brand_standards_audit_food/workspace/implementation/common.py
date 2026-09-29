"""Shared value helpers: timestamps, decimal precision, record mutation."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import g

import db

CENT = Decimal("0.01")


def q2(value):
    """Round half up to exactly two decimal places (PRD 2.6)."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def dec(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def clamp(value, low, high):
    if value < low:
        return low
    if value > high:
        return high
    return value


def fmt_dt(value):
    """ISO 8601 UTC with exactly three fractional digits (PRD 2.5)."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    d = value.astimezone(timezone.utc)
    return d.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (d.microsecond // 1000)


def parse_dt(raw):
    """Parse a client supplied ISO 8601 instant.  Returns None when invalid."""
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text:
        return None
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def hours_between(start, end):
    """Signed hours from ``start`` to ``end`` rounded half up to 2dp."""
    seconds = Decimal(str((end - start).total_seconds()))
    return q2(seconds / Decimal(3600))


def days(count):
    return timedelta(days=count)


def hours(count):
    return timedelta(hours=count)


def minutes(count):
    return timedelta(minutes=count)


def touch(record):
    """Mark a versioned record as mutated: refresh updated_at, bump version.

    A record is bumped at most once per request, so one API operation advances
    a record's version by exactly one however many of its fields moved.
    """
    if record is None or "version" not in record:
        return
    touched = getattr(g, "_touched", None)
    if touched is None:
        touched = set()
        g._touched = touched
    if record["id"] in touched:
        return
    touched.add(record["id"])
    record["updated_at"] = db.store.clock
    record["version"] = record["version"] + 1


def set_if_changed(record, field, value):
    """Assign a derived field, touching the record only when it really moves."""
    if record.get(field) != value:
        record[field] = value
        touch(record)
        return True
    return False
