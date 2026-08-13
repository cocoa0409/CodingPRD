"""In-memory data store and the logical clock.

The store starts completely empty on every boot — no seeding. Every entity
any test needs is constructed through the declared API surface.

The logical clock defaults to exactly 2026-08-01T00:00:00Z at startup and
only moves when a FundAdmin sets it via POST /_clock/set_current_utc.
"""

import uuid
from datetime import datetime, timezone

DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.funds = {}
        self.employers = {}
        self.members = {}
        self.reports = {}
        self.lines = {}
        self.purchases = {}
        self.payments = {}
        self.retirement_apps = {}
        self.disability_apps = {}
        self.benefits = {}
        self.beneficiaries = {}
        self.seq = 0
        self.clock = DEFAULT_CLOCK


store = Store()


def now():
    """Current logical-clock instant (aware UTC datetime)."""
    return store.clock


def set_clock(dt):
    store.clock = dt


def next_seq():
    store.seq += 1
    return store.seq


def new_id():
    return str(uuid.uuid4())


def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits (common fields)."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def fmt_dt(dt):
    """ISO 8601 UTC for action timestamps (quote expiry, decided_at, ...).

    Seconds precision when the instant lands on a whole second so that e.g.
    quote_expires_at renders as 2026-10-30T00:00:00Z; milliseconds otherwise.
    """
    if dt.microsecond == 0:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return fmt_ts(dt)


def make_entity(fields):
    """Create a persisted record with the common fields (id/created_at/
    updated_at/version) plus an internal monotonic _seq used to break
    created_at ties deterministically."""
    ts = fmt_ts(store.clock)
    e = {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }
    e.update(fields)
    return e


def touch(e):
    """Record a mutation: bump version by exactly 1 and refresh updated_at."""
    e["updated_at"] = fmt_ts(store.clock)
    e["version"] += 1


def sort_key(e):
    """Default list ordering: created_at ascending, creation order as tiebreak."""
    return (e["created_at"], e["_seq"])


def public(e):
    """Strip internal bookkeeping fields for serialization."""
    return {k: v for k, v in e.items() if not k.startswith("_")}


def current_fund():
    """The fund governing plan-wide thresholds (earnings limit). The domain
    model assumes a single fund; with several, the earliest created governs."""
    if not store.funds:
        return None
    return min(store.funds.values(), key=lambda f: f["_seq"])
