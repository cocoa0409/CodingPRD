"""In-memory data store and the service logical clock.

Storage is process-local dicts keyed by id. The store starts EMPTY on every
boot — no seeding, no disk persistence, ever. Fields prefixed with "_" are
internal (parsed dates, insertion sequence) and never serialized.
"""
import uuid
from datetime import datetime, timezone

from util import fmt_ts

# PRD 2.4: before any set_current_utc call the logical clock reads exactly
# 2026-08-01T00:00:00Z and never falls back to wall-clock time.
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.clock = DEFAULT_CLOCK
        self.seq = 0
        self.carriers = {}
        self.configs = {}
        self.stations = {}
        self.vehicles = {}
        self.credentials = {}
        self.subscriptions = {}
        self.snapshots = {}
        self.events = {}
        self.disputes = {}
        self.overrides = {}
        self.invoices = {}
        self.reports = {}

    def next_seq(self):
        self.seq += 1
        return self.seq


store = Store()


def now():
    return store.clock


def today():
    return store.clock.date()


def new_id():
    # PRD 2.5: server-minted UUID, canonical 8-4-4-4-2 form, no type prefix.
    return str(uuid.uuid4())


def stamp(rec):
    """Set created_at/updated_at on a fresh full-identity-block record."""
    ts = fmt_ts(store.clock)
    rec["created_at"] = ts
    rec["updated_at"] = ts


def stamp_feed(rec):
    """Append-only feed/audit records carry only id and created_at."""
    rec["created_at"] = fmt_ts(store.clock)


def bump(rec):
    """PRD 2.5: version increments by one on every mutation; updated_at refreshes."""
    rec["version"] += 1
    rec["updated_at"] = fmt_ts(store.clock)


def public(rec):
    """Strip internal "_" keys for serialization."""
    return {k: v for k, v in rec.items() if not k.startswith("_")}
