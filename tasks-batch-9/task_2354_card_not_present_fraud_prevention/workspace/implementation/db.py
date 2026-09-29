"""In-memory data store and the server-owned logical clock.

Storage is process-local Python dicts only. Nothing is seeded, preloaded or
persisted: every collection starts empty on every boot and every row is created
through the declared API surface.
"""

import uuid
from datetime import datetime

from flask import g

# PRD 2.4: before any client touches it, the logical clock reads exactly this
# instant, and it never falls back to wall-clock time.
CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0)


class Store(object):
    def __init__(self):
        self.customers = {}
        self.analysts = {}
        self.devices = {}
        self.addresses = {}
        self.rule_packs = {}
        self.fraud_rules = {}
        self.risk_models = {}
        self.assessments = {}
        self.review_cases = {}
        self.auth_events = {}
        self.chargebacks = {}
        self.policy_exceptions = {}
        self.current_utc = CLOCK_EPOCH
        self._seq = 0

    # ------------------------------------------------------------------ clock
    def now(self):
        return self.current_utc

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def new_id():
    """Server-minted UUID with no type prefix (PRD 2.5)."""
    return str(uuid.uuid4())


def _touched_set():
    touched = getattr(g, "_touched_rows", None)
    if touched is None:
        touched = set()
        g._touched_rows = touched
    return touched


def mark_fresh(rec):
    """Record created in this request: version stays at 1 for the whole request."""
    _touched_set().add(id(rec))


def touch(rec):
    """Stamp updated_at and increment version once per row per request (PRD 2.5)."""
    touched = _touched_set()
    key = id(rec)
    if key in touched:
        return
    touched.add(key)
    rec["updated_at"] = db.now()
    rec["version"] = rec.get("version", 1) + 1


def sort_rows(rows):
    """Default collection order: created_at ascending (insertion-stable)."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
