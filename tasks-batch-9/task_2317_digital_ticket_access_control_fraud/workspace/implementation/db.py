"""In-memory data store.

Storage is process-local Python dicts only. The store boots EMPTY on every
process start: nothing is seeded, preloaded or hardcoded. Every entity a client
observes is created through the declared API surface.
"""

import threading

from util import new_id, now_iso3, parse_dt, LOGICAL_CLOCK_EPOCH_ZERO


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.reset()

    def reset(self):
        self.events = {}
        self.zones = {}
        self.gates = {}
        self.patrons = {}
        self.tickets = {}
        self.transfers = {}
        self.listings = {}
        self.sessions = {}
        self.scan_events = {}
        self.credential_requests = {}
        self.incidents = {}
        self.reports = {}
        self.audit_entries = {}
        # The logical clock (PRD 2.4). Never falls back to wall-clock time.
        self.clock = parse_dt(LOGICAL_CLOCK_EPOCH_ZERO)
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def base_record(versioned=True):
    """Common resource properties (PRD 2.5)."""
    rec = {
        "id": new_id(),
        "created_at": now_iso3(),
    }
    if versioned:
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1
    rec["_seq"] = db.next_seq()
    return rec


def touch(rec):
    """Any mutation of a stored field refreshes updated_at and bumps version."""
    rec["updated_at"] = now_iso3()
    rec["version"] = rec.get("version", 0) + 1
    return rec


def public(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def sort_created_asc(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
