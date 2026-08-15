"""In-memory data store. A fresh Store instance is created per process boot;
the per-test-server isolation restarts the process before every test, so all
state resets naturally. No seeding of any entity happens here."""

import uuid
from datetime import datetime, timezone

UTC = timezone.utc

START_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)


class Store:
    def __init__(self):
        # Logical clock: starts exactly at 2026-08-01T00:00:00Z, never wall time.
        self.clock = START_CLOCK
        self.ops_run_index = 0
        self.seq = 0  # monotonic insertion counter for stable created_at tie-breaks

        self.channels = {}
        self.tax_forms = {}
        self.revenue_events = {}
        self.payouts = {}
        self.tiers = {}
        self.viewers = {}
        self.subscriptions = {}
        self.perk_grants = {}
        self.moderators = {}
        self.mod_actions = {}
        self.strikes = {}
        self.deals = {}
        self.deliverables = {}
        self.streams = {}
        self.grants = {}


store = Store()


def now():
    return store.clock


def new_id():
    return str(uuid.uuid4())


def new_entity(**fields):
    """Create a record with the common fields: id, created_at, updated_at, version."""
    store.seq += 1
    ts = store.clock
    e = {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": store.seq,
    }
    e.update(fields)
    return e


def new_ledger_event(**fields):
    """RevenueEvent: append-only ledger entry with only id + created_at from the
    common set (no updated_at, no version)."""
    store.seq += 1
    e = {
        "id": new_id(),
        "created_at": store.clock,
        "_seq": store.seq,
    }
    e.update(fields)
    return e


def touch(e):
    """Refresh updated_at to the logical clock and bump version by exactly 1."""
    e["updated_at"] = store.clock
    e["version"] += 1
