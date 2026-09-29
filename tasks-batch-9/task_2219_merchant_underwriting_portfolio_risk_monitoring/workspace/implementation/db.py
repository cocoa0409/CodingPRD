"""In-memory data store.

Every collection is a plain dict keyed by the entity id. The store is created
empty on every boot and NOTHING is ever seeded, preloaded or hardcoded here:
tests build all preconditions through the declared API surface.
"""
from datetime import datetime, timezone

from util import fmt_date, iso_ts, new_id, now_ts

# PRD 2.4: before any caller moves it, the logical clock reads exactly this.
CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

# Record types that carry only id + created_at (PRD 2.4).
NO_VERSION_TYPES = ("ProhibitedCategoryRule", "ReserveLedgerEntry", "MerchantDayActivity")


class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        self.applications = {}
        self.verifications = {}
        self.owners = {}
        self.category_rules = {}
        self.assessments = {}
        self.merchants = {}
        self.reserve_accounts = {}
        self.ledger_entries = {}
        self.batches = {}
        self.day_activity = {}
        self.alerts = {}
        self.programs = {}
        self.terminations = {}
        self.appeals = {}
        self.forecasts = {}
        self.clock = CLOCK_EPOCH
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq

    # ---- logical clock ------------------------------------------------
    def clock_iso(self):
        return iso_ts(self.clock)

    def clock_date(self):
        return fmt_date(self.clock.astimezone(timezone.utc).date())


db = Store()


def new_row(versioned=True):
    """Allocate a fresh row with its system-managed audit fields."""
    stamp = now_ts()
    row = {"id": new_id(), "created_at": stamp}
    if versioned:
        row["updated_at"] = stamp
        row["version"] = 1
    row["_seq"] = db.next_seq()
    return row


def by_seq(rows):
    """created_at ascending (the internal sequence is a stable proxy)."""
    return sorted(rows, key=lambda r: r["_seq"])


def serialize(row):
    return {k: v for k, v in row.items() if not k.startswith("_")}


def serialize_all(rows):
    return [serialize(r) for r in rows]
