"""In-memory data store, logical clock, and id / timestamp / rounding helpers.

The store is process-local and starts completely empty on every boot: nothing is
seeded, preloaded or hardcoded here.  Every entity is created by an API call.
"""

import itertools
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import g

# --------------------------------------------------------------------------
# Timestamps -- ISO 8601 UTC with exactly three fractional-second digits.
# --------------------------------------------------------------------------

CLOCK_EPOCH_DEFAULT = "2026-08-01T00:00:00Z"


def parse_instant(value):
    """Parse an ISO 8601 instant (or a bare calendar date) into aware UTC.

    Raises ValueError when the value is not a usable ISO 8601 string.
    """
    if not isinstance(value, str):
        raise ValueError("not a string")
    text = value.strip()
    if not text:
        raise ValueError("empty")
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise ValueError("unparseable instant: %s" % value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def fmt_instant(moment):
    if moment is None:
        return None
    moment = moment.astimezone(timezone.utc)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (moment.microsecond // 1000)


def add_days(moment, days):
    return moment + timedelta(days=days)


def day_of(moment):
    """Calendar date of an instant, as a date object."""
    return moment.astimezone(timezone.utc).date()


def calendar_days_between(later, earlier):
    """Whole calendar days from ``earlier``'s date to ``later``'s date."""
    return (day_of(later) - day_of(earlier)).days


def floor_days_between(later, earlier):
    """Whole elapsed days between two instants, floored."""
    delta = later - earlier
    return int(delta.total_seconds() // 86400)


def midnight(moment):
    """Start of the calendar day that contains ``moment``."""
    day = day_of(moment)
    return datetime(day.year, day.month, day.day, tzinfo=timezone.utc)


class LogicalClock(object):
    """The service's only source of time; the host wall clock is never read."""

    def __init__(self):
        self.current = parse_instant(CLOCK_EPOCH_DEFAULT)

    def set(self, moment):
        previous = self.current
        self.current = moment
        return previous


CLOCK = LogicalClock()


def now():
    return CLOCK.current


def now_str():
    return fmt_instant(CLOCK.current)


# --------------------------------------------------------------------------
# Money / ratio arithmetic -- integer cents, ROUND_HALF_UP, never a float.
# --------------------------------------------------------------------------


def round_half_up_div(numerator, denominator):
    """round_half_up(numerator / denominator) as an int."""
    quotient = Decimal(int(numerator)) / Decimal(int(denominator))
    return int(quotient.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def apply_bps(amount_cents, bps):
    """round_half_up(amount_cents * bps / 10000) as an int."""
    return round_half_up_div(int(amount_cents) * int(bps), 10000)


def ratio_4dp(numerator, denominator):
    """round_half_up(numerator / denominator) to four decimal places."""
    quotient = Decimal(int(numerator)) / Decimal(int(denominator))
    return quotient.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def as_number(decimal_value):
    """Render a Decimal as a JSON number."""
    return float(decimal_value)


# --------------------------------------------------------------------------
# Tables
# --------------------------------------------------------------------------

TABLES = (
    "dealers",
    "credit_lines",
    "curtailment_tiers",
    "inventory_units",
    "funding_advances",
    "curtailment_obligations",
    "aging_exceptions",
    "audits",
    "observations",
    "incidents",
    "remittances",
    "covenant_tests",
    "remedy_actions",
)

STORE = {name: {} for name in TABLES}

_SEQUENCE = itertools.count(1)


def new_id():
    return str(uuid.uuid4())


def insert(table, record, versioned=True):
    """Store a new record, stamping id, created_at and (optionally) version."""
    record.setdefault("id", new_id())
    record["created_at"] = now_str()
    if versioned:
        record["updated_at"] = record["created_at"]
        record["version"] = 1
    record["_seq"] = next(_SEQUENCE)
    STORE[table][record["id"]] = record
    return record


def get(table, record_id):
    if not isinstance(record_id, str):
        return None
    return STORE[table].get(record_id)


def rows(table):
    """All records of a table in creation order."""
    return sorted(STORE[table].values(), key=lambda row: row["_seq"])


def where(table, **criteria):
    result = []
    for row in rows(table):
        if all(row.get(key) == value for key, value in criteria.items()):
            result.append(row)
    return result


def first(table, **criteria):
    matches = where(table, **criteria)
    return matches[0] if matches else None


def touch(record):
    """Advance updated_at / version once per request for a mutated record."""
    if record is None or "version" not in record:
        return record
    try:
        seen = g._touched
    except (AttributeError, RuntimeError):
        seen = None
    if seen is None:
        seen = set()
        try:
            g._touched = seen
        except RuntimeError:
            pass
    key = id(record)
    if key in seen:
        record["updated_at"] = now_str()
        return record
    seen.add(key)
    record["updated_at"] = now_str()
    record["version"] = int(record["version"]) + 1
    return record


def public(record, fields):
    """Project a stored record onto its declared public field list."""
    return {name: record.get(name) for name in fields}
