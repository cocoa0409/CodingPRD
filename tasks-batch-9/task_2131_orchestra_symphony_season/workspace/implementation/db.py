"""In-memory data store and the logical UTC clock.

The store starts completely empty on every boot.  Nothing is seeded, preloaded
or hardcoded here; every entity is created by clients through the declared
endpoints.
"""

import itertools
import uuid
from datetime import datetime, timezone

# PRD 2.4: before any client sets it, the logical clock reads exactly
# 2026-08-01T00:00:00Z and never falls back to wall-clock time.
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store(object):
    def __init__(self):
        self._seq = itertools.count(1)
        self.seasons = {}
        self.venues = {}
        self.sections = {}
        self.concerts = {}
        self.contracts = {}
        self.musicians = {}
        self.agreements = {}
        self.services = {}
        self.engagements = {}
        self.patrons = {}
        self.packages = {}
        self.orders = {}
        self.adbookings = {}
        self.clock = DEFAULT_CLOCK

    def next_seq(self):
        return next(self._seq)


db = Store()


def new_id():
    """Server-minted UUID string with no type prefix (PRD 2.4)."""
    return str(uuid.uuid4())


def now():
    """Current instant on the logical UTC clock."""
    return db.clock


def iso(dt):
    """ISO 8601 UTC timestamp with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def now_iso():
    return iso(db.clock)


def clock_year():
    return db.clock.astimezone(timezone.utc).year
