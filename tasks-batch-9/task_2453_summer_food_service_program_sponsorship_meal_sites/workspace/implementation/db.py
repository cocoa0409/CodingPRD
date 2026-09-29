"""In-memory data store, logical clock and common-field helpers.

Storage is process-local Python dicts keyed by id.  Nothing is persisted and
nothing is seeded: every boot starts completely empty and all state is built by
callers through the declared endpoints (PRD sec 2.4 / sec 2.5).
"""

import itertools
import uuid
from datetime import date, datetime, timedelta, timezone

# --------------------------------------------------------------------------
# Logical clock (PRD sec 2.4)
# --------------------------------------------------------------------------
# "Nothing in this system reads the wall clock."  The logical clock is the
# single source of "now" and is initialised to exactly this instant at process
# start, before any caller sets it explicitly.
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class LogicalClock(object):
    def __init__(self):
        self.current = DEFAULT_CLOCK

    def set(self, moment):
        self.current = moment.astimezone(timezone.utc)

    def now(self):
        return self.current

    def now_iso(self):
        return to_iso(self.current)

    def today(self):
        return self.current.date()


clock = LogicalClock()


# --------------------------------------------------------------------------
# Timestamp / date helpers
# --------------------------------------------------------------------------
def to_iso(moment):
    """ISO 8601 UTC with exactly three fractional-second digits (PRD sec 2.2)."""
    moment = moment.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        moment.year,
        moment.month,
        moment.day,
        moment.hour,
        moment.minute,
        moment.second,
        moment.microsecond // 1000,
    )


def parse_datetime(raw):
    """Parse an ISO 8601 instant.  Returns an aware UTC datetime or None."""
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text:
        return None
    if text.endswith("z") or text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_date(raw):
    """Parse a strict YYYY-MM-DD calendar date.  Returns a date or None."""
    if not isinstance(raw, str) or len(raw) != 10:
        return None
    try:
        return date(int(raw[0:4]), int(raw[5:7]), int(raw[8:10])) if (
            raw[4] == "-" and raw[7] == "-"
        ) else None
    except (ValueError, TypeError):
        return None


def date_iso(value):
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return "%04d-%02d-%02d" % (value.year, value.month, value.day)


def parse_hhmm(raw):
    """Parse a strict HH:MM clock time into minutes past midnight, or None."""
    if not isinstance(raw, str) or len(raw) != 5 or raw[2] != ":":
        return None
    try:
        hours = int(raw[0:2])
        minutes = int(raw[3:5])
    except ValueError:
        return None
    if hours < 0 or hours > 23 or minutes < 0 or minutes > 59:
        return None
    return hours * 60 + minutes


def parse_year_month(raw):
    """Parse 'YYYY-MM' into a (year, month) tuple, or None."""
    if not isinstance(raw, str) or len(raw) != 7 or raw[4] != "-":
        return None
    try:
        year = int(raw[0:4])
        month = int(raw[5:7])
    except ValueError:
        return None
    if month < 1 or month > 12:
        return None
    return (year, month)


def last_day_of_month(year, month):
    if month == 12:
        first_next = date(year + 1, 1, 1)
    else:
        first_next = date(year, month + 1, 1)
    return first_next - timedelta(days=1)


def add_months(year, month, count):
    total = (year * 12) + (month - 1) + count
    return (total // 12, (total % 12) + 1)


def new_id():
    """Opaque UUID identifier, no prefix (PRD sec 2.5)."""
    return str(uuid.uuid4())


# --------------------------------------------------------------------------
# Store
# --------------------------------------------------------------------------
class Store(object):
    COLLECTIONS = (
        "sponsors",
        "area_records",
        "budgets",
        "advances",
        "sites",
        "days",
        "count_entries",
        "holding_logs",
        "visits",
        "actions",
        "claims",
        "line_items",
    )

    def __init__(self):
        for name in self.COLLECTIONS:
            setattr(self, name, {})
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


store = Store()


# --------------------------------------------------------------------------
# Common fields (PRD sec 2.5)
# --------------------------------------------------------------------------
def new_row(fields, versioned=True):
    row = dict(fields)
    row["id"] = new_id()
    row["created_at"] = clock.now_iso()
    row["_seq"] = store.next_seq()
    if versioned:
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    return row


def touch(row):
    """Record a mutation: refresh updated_at and increment version by one."""
    if "version" in row:
        row["updated_at"] = clock.now_iso()
        row["version"] = row["version"] + 1
    return row


def apply_changes(row, changes):
    """Write changes, bumping version/updated_at only when something changed."""
    changed = False
    for key, value in changes.items():
        if row.get(key) != value:
            row[key] = value
            changed = True
    if changed:
        touch(row)
    return changed


def sort_key(row):
    """Default deterministic ordering: created_at ascending (PRD sec 2.3/2.5)."""
    return (row["created_at"], row["_seq"])


def ordered(rows):
    return sorted(rows, key=sort_key)
