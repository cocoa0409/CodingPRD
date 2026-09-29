"""In-memory data store and the logical clock.

The store starts EMPTY on every boot: no entity is ever seeded, preloaded or
hardcoded.  Every row a test needs is built through the declared API surface.
"""

import itertools
import uuid
from datetime import datetime, timezone

# PRD 2.4: the logical clock starts at this fixed instant and never falls back
# to real wall-clock time.
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
DEFAULT_CLOCK_RAW = "2026-08-01T00:00:00.000Z"


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.policies = {}
        self.counterparties = {}
        self.stations = {}
        self.contracts = {}
        self.forecasts = {}
        self.programs = {}
        self.instruments = {}
        self.postings = {}
        self.tests = {}
        self.mtm_runs = {}
        self.legs = {}
        self.directives = {}
        self.exceptions = {}
        self._seq = itertools.count(1)
        self.clock = DEFAULT_CLOCK
        self.clock_raw = DEFAULT_CLOCK_RAW


db = Store()


def next_seq():
    return next(db._seq)


def new_id():
    return str(uuid.uuid4())


def fmt_ts(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_iso():
    """Current logical-clock instant, ISO 8601 UTC with three fractional digits."""
    return fmt_ts(db.clock)


def clock_date():
    return db.clock.date()


def rows_in_order(table):
    """All rows of a table in created_at ASC order (stable via the seq counter)."""
    return sorted(table.values(), key=lambda r: r["_seq"])
