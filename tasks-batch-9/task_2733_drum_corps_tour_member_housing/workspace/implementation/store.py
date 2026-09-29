"""In-memory data store and logical clock.

Storage is process-local Python dicts only.  The store starts completely
EMPTY on every boot; nothing is ever seeded, preloaded or hardcoded here.
Tests build all state through the declared API surface.
"""
import itertools
import re
import threading
import uuid
from datetime import date, datetime, timedelta, timezone

# PRD 2.4: before any operator sets it, the logical clock reads exactly
# 2026-08-01T00:00:00Z.  It must never fall back to host wall-clock time.
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

LOCK = threading.RLock()


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.seasons = {}
        self.members = {}
        self.contracts = {}
        self.plans = {}
        self.payments = {}
        self.schools = {}
        self.agreements = {}
        self.housing = {}
        self.stops = {}
        self.bookings = {}
        self.volunteers = {}
        self.staff = {}
        self.settlements = {}
        self.clock = DEFAULT_CLOCK
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


db = Store()


# --------------------------------------------------------------------------
# logical clock helpers
# --------------------------------------------------------------------------
def clock_instant():
    return db.clock


def clock_date():
    return db.clock.date()


def fmt_instant(dt):
    """ISO 8601 UTC with exactly three fractional-second digits (PRD 2.4)."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def clock_iso():
    return fmt_instant(db.clock)


def fmt_date(d):
    if d is None:
        return None
    return "%04d-%02d-%02d" % (d.year, d.month, d.day)


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_date(value):
    """Parse a strict YYYY-MM-DD calendar date.  Returns None when invalid."""
    if not isinstance(value, str) or not _DATE_RE.match(value):
        return None
    try:
        return date(int(value[0:4]), int(value[5:7]), int(value[8:10]))
    except ValueError:
        return None


def parse_instant(value):
    """Parse a full ISO 8601 UTC instant.  Returns None when invalid."""
    if not isinstance(value, str) or not value:
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


def days_between(a, b):
    """Whole-day arithmetic: b - a in days."""
    return (b - a).days


def add_days(d, n):
    return d + timedelta(days=n)


def minus_years(d, years):
    """Shift a calendar date back by whole years, clamping Feb 29 -> Feb 28."""
    try:
        return d.replace(year=d.year - years)
    except ValueError:
        return d.replace(year=d.year - years, day=28)


# --------------------------------------------------------------------------
# record helpers -- common resource properties (PRD 2.4)
# --------------------------------------------------------------------------
def new_record():
    stamp = clock_iso()
    return {
        "id": str(uuid.uuid4()),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
        "_seq": db.next_seq(),
    }


def touch(record):
    """Advance version by exactly 1 and refresh updated_at to the clock."""
    record["version"] = record["version"] + 1
    record["updated_at"] = clock_iso()


def sorted_records(collection):
    """Default list ordering: created_at ascending (stable by insertion)."""
    return sorted(collection.values(), key=lambda r: (r["created_at"], r["_seq"]))
