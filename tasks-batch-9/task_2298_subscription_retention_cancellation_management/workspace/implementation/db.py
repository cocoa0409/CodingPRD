"""In-memory data store, logical clock and per-request transaction support.

Storage is process-local Python dicts keyed by id.  The store starts EMPTY on
every boot: nothing is seeded, preloaded or hardcoded.
"""
import copy
import uuid
from datetime import timedelta

from constants import DEFAULT_CLOCK_UTC

COLLECTIONS = (
    "plans",
    "save_offer_templates",
    "subscribers",
    "payment_methods",
    "subscriptions",
    "invoices",
    "dunning_attempts",
    "cancellation_sessions",
    "save_offer_grants",
    "subscription_modifications",
    "compliance_notices",
    "winback_campaigns",
    "winback_targets",
    "cohort_snapshots",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock = DEFAULT_CLOCK_UTC
        self.seq = 0

    # ---- logical clock ----
    def now(self):
        return self.clock

    def set_clock(self, instant):
        self.clock = instant

    def next_seq(self):
        self.seq += 1
        return self.seq

    # ---- transaction (all-or-nothing per request) ----
    def begin(self):
        snap = {name: copy.deepcopy(getattr(self, name)) for name in COLLECTIONS}
        snap["__clock__"] = self.clock
        snap["__seq__"] = self.seq
        return snap

    def rollback(self, snap):
        if not snap:
            return
        for name in COLLECTIONS:
            setattr(self, name, snap[name])
        self.clock = snap["__clock__"]
        self.seq = snap["__seq__"]


store = Store()


def new_id():
    return str(uuid.uuid4())


def base_record(versioned=True):
    """Common system fields (PRD §2.4)."""
    rec = {
        "id": new_id(),
        "created_at": store.now(),
        "_seq": store.next_seq(),
    }
    if versioned:
        rec["updated_at"] = store.now()
        rec["version"] = 1
    return rec


def touch(rec):
    """Refresh updated_at and increment version (PRD §2.4/§2.10)."""
    rec["updated_at"] = store.now()
    rec["version"] = rec.get("version", 1) + 1
    return rec


def ordered(records):
    """Default ordering: created_at ascending (stable by creation sequence)."""
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))


def days(n):
    return timedelta(days=n)


def hours(n):
    return timedelta(hours=n)
