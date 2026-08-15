"""In-memory data store and the logical clock.

The store is module-level and starts empty on every process boot. Nothing is
seeded. The logical clock defaults to 2026-08-01T00:00:00Z and is only ever
moved by POST /escrow/_clock/set_current_utc; the server never reads the host
wall clock.
"""

import uuid
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.files = {}
        self.holdbacks = {}
        self.approvals = {}
        self.bids = {}
        self.work_orders = {}
        self.inspections = {}
        self.draws = {}
        self.extensions = {}
        self.disputes = {}
        self.pledges = {}
        self.ledger = {}
        self.ledger_by_hb = {}
        self.ix = 0  # global insertion counter, tie-breaks equal created_at
        self.clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


store = Store()


def new_id():
    return str(uuid.uuid4())


def next_ix():
    store.ix += 1
    return store.ix


def now():
    return store.clock


def fmt_dt(dt):
    """ISO 8601 UTC instant with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_iso():
    return fmt_dt(store.clock)


def today():
    """UTC calendar date of the logical clock."""
    return store.clock.date()
