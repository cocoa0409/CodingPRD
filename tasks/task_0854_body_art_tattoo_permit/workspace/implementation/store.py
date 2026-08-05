"""In-memory storage, the logical clock and the per-request version tracker.

The store starts EMPTY on every boot.  Nothing is seeded, preloaded or
hardcoded here; every row is created through a declared API endpoint.
"""

import threading

import config
from util import parse_ts

LOCK = threading.RLock()

# ---------------------------------------------------------------------------
# Collections.  Each maps id -> record dict; Python dicts preserve insertion
# order, which is also created_at ASC order because created_at is stamped from
# the logical clock at insertion time.
# ---------------------------------------------------------------------------
establishments = {}
artists = {}
plan_reviews = {}
inspections = {}
violations = {}
sterilization_records = {}
minor_consents = {}
procedure_logs = {}
complaints = {}
infection_reports = {}
enforcement_actions = {}
renewal_applications = {}

COLLECTIONS = {
    "establishments": establishments,
    "artists": artists,
    "plan-reviews": plan_reviews,
    "inspections": inspections,
    "violations": violations,
    "sterilization-records": sterilization_records,
    "minor-consents": minor_consents,
    "procedure-logs": procedure_logs,
    "complaints": complaints,
    "infection-reports": infection_reports,
    "enforcement-actions": enforcement_actions,
    "renewal-applications": renewal_applications,
}

# ---------------------------------------------------------------------------
# Logical clock.  The server never reads wall-clock time.
# ---------------------------------------------------------------------------
_clock = {"now": parse_ts(config.LOGICAL_CLOCK_DEFAULT_UTC)}


def now():
    return _clock["now"]


def set_now(dt):
    _clock["now"] = dt


def reset_clock():
    _clock["now"] = parse_ts(config.LOGICAL_CLOCK_DEFAULT_UTC)


def sorted_rows(collection):
    """created_at ASC; ties broken by insertion order."""
    return sorted(collection.values(), key=lambda r: (r["created_at"], r["_seq"]))


_seq = {"n": 0}


def next_seq():
    _seq["n"] += 1
    return _seq["n"]


# ---------------------------------------------------------------------------
# Version tracker.  PRD §2.4: every mutation that touches a record increments
# its version by exactly one and refreshes updated_at — including mutations
# that arrive as derived-field recomputation.  The tracker snapshots every
# record a request touches and bumps exactly once at the end of the request.
# ---------------------------------------------------------------------------
_IGNORED = ("version", "updated_at")


def _snapshot(rec):
    return {k: v for k, v in rec.items() if k not in _IGNORED}


class Tracker:
    def __init__(self):
        self.watched = {}
        self.forced = set()
        self.fresh = set()

    def mark_new(self, rec):
        """A record created during this request opens at version 1 and is never
        bumped by the tracker, however many derived fields are then written."""
        self.fresh.add(id(rec))
        return rec

    def watch(self, rec):
        if rec is None:
            return rec
        if "version" not in rec:
            return rec
        key = id(rec)
        if key in self.fresh:
            return rec
        if key not in self.watched:
            self.watched[key] = (rec, _snapshot(rec))
        return rec

    def force(self, rec):
        if rec is None or "version" not in rec:
            return rec
        if id(rec) in self.fresh:
            return rec
        self.watch(rec)
        self.forced.add(id(rec))
        return rec

    def commit(self, stamp):
        for key, (rec, snap) in self.watched.items():
            if key in self.forced or _snapshot(rec) != snap:
                rec["version"] = rec.get("version", 1) + 1
                rec["updated_at"] = stamp
