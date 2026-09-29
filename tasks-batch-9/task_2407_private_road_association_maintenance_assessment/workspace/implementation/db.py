"""In-memory data store, logical clock, and row helpers.

Storage is process-local Python dicts only. The store starts completely empty on
every boot: no entity is ever seeded, preloaded or hardcoded here. Tests build
all preconditions through the declared API surface.
"""

import itertools
import uuid
from datetime import datetime, timezone, date, timedelta
from fractions import Fraction

# PRD 2.4: before any client sets it, the logical clock reads exactly
# 2026-08-01T00:00:00Z and never falls back to real wall-clock time.
INITIAL_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store(object):
    """All twelve persisted record types plus the logical clock."""

    def __init__(self):
        self.associations = {}
        self.road_segments = {}
        self.parcels = {}
        self.members = {}
        self.assessment_rolls = {}
        self.assessment_charges = {}
        self.proposals = {}
        self.ballots = {}
        self.projects = {}
        self.contractor_bids = {}
        self.delinquency_actions = {}
        self.connection_requests = {}
        self.clock = INITIAL_CLOCK
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


db = Store()


# ---------------------------------------------------------------------------
# logical clock / timestamp helpers
# ---------------------------------------------------------------------------

def now_dt():
    return db.clock


def set_clock(dt):
    db.clock = dt.astimezone(timezone.utc)


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def now_iso():
    return iso(db.clock)


def clock_date():
    return db.clock.astimezone(timezone.utc).date()


def date_str(d):
    if d is None:
        return None
    return "%04d-%02d-%02d" % (d.year, d.month, d.day)


def parse_date(value):
    """Strict ISO 8601 calendar date (YYYY-MM-DD). Returns None on failure."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if len(text) != 10 or text[4] != "-" or text[7] != "-":
        return None
    try:
        return date(int(text[0:4]), int(text[5:7]), int(text[8:10]))
    except (ValueError, TypeError):
        return None


def parse_datetime(value):
    """ISO 8601 instant. Returns a tz-aware UTC datetime, or None on failure."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def add_days(d, n):
    return d + timedelta(days=n)


def day_diff(later, earlier):
    return (later - earlier).days


# ---------------------------------------------------------------------------
# row helpers
# ---------------------------------------------------------------------------

def new_id():
    return str(uuid.uuid4())


def new_row(fields):
    """Create a row carrying the four system-managed properties of PRD 2.4."""
    row = {
        "id": new_id(),
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "version": 1,
        "_seq": db.next_seq(),
    }
    row.update(fields)
    return row


def touch(row):
    """A mutation: refresh updated_at and increment version by one."""
    row["updated_at"] = now_iso()
    row["version"] = int(row["version"]) + 1


def by_seq(rows):
    return sorted(rows, key=lambda r: r["_seq"])


def to_fraction(value):
    """Exact rational conversion that never introduces binary float error."""
    if isinstance(value, Fraction):
        return value
    if isinstance(value, int):
        return Fraction(value)
    if isinstance(value, float):
        return Fraction(str(value))
    return Fraction(str(value))
