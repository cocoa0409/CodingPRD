"""In-memory data store, logical clock and row helpers.

Storage is pure Python dicts held in this module's single ``DB`` instance.  The
store starts EMPTY on every boot: nothing is seeded, preloaded or hardcoded.
"""

import itertools
import uuid
from datetime import datetime, timedelta, timezone

INITIAL_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

# Every collection the service persists.  One dict per entity, keyed by id.
TABLES = (
    "composers",
    "agreements",
    "compositions",
    "tiers",
    "licensees",
    "sync_requests",
    "licenses",
    "blankets",
    "usage_reports",
    "cue_sheets",
    "matches",
    "claims",
    "statements",
    "ledger",
)


def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD §2.4)."""
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


def parse_ts(value):
    """Parse an ISO 8601 instant; returns None when unparseable."""
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


class Database(object):
    def __init__(self):
        self.reset()

    def reset(self):
        for name in TABLES:
            setattr(self, name, {})
        self.search_profile = None
        self.clock = INITIAL_CLOCK
        self._seq = itertools.count(1)

    # -- clock -----------------------------------------------------------
    @property
    def now(self):
        return self.clock

    @property
    def now_iso(self):
        return fmt_ts(self.clock)

    # -- row helpers -----------------------------------------------------
    def next_seq(self):
        return next(self._seq)

    def new_row(self, versioned=True):
        """A fresh row carrying the common system fields (PRD §2.4)."""
        stamp = self.now_iso
        row = {"id": str(uuid.uuid4()), "created_at": stamp}
        if versioned:
            row["updated_at"] = stamp
            row["version"] = 1
        row["_seq"] = self.next_seq()
        row["_created_dt"] = self.clock
        return row


DB = Database()


def sort_rows(rows):
    """Default list ordering: created_at ascending (insertion order breaks ties)."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def public(row):
    """Strip internal bookkeeping keys."""
    return {k: v for k, v in row.items() if not k.startswith("_")}


def add_months(dt, months):
    """Calendar-month arithmetic with day clamping to the end of the month."""
    month_index = dt.month - 1 + months
    year = dt.year + month_index // 12
    month = month_index % 12 + 1
    day = min(dt.day, _days_in_month(year, month))
    return dt.replace(year=year, month=month, day=day)


def _days_in_month(year, month):
    if month == 12:
        nxt = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        nxt = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    return (nxt - timedelta(days=1)).day


def date_only(dt):
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)
