"""Capacity accounting: the current tranche and the lifetime aggregate
(PRD section 2.7)."""
from db import STORE, touch

NON_TERMINAL_ALLOCATION_STATUSES = ("ACTIVE", "EXHAUSTED")


def current_tranche(program_id):
    """At most one allocation per program may be non-terminal (ACTIVE or
    EXHAUSTED); returns it, or None."""
    cands = [
        a for a in STORE.capacity_allocations.values()
        if a["program_id"] == program_id and a["status"] in NON_TERMINAL_ALLOCATION_STATUSES
    ]
    if not cands:
        return None
    cands.sort(key=lambda a: a["_seq"])
    return cands[-1]


def reconcile_tranche(t):
    """consumed == allocated -> EXHAUSTED; a release back below the allocation
    flips EXHAUSTED -> ACTIVE. Terminal statuses are never reconciled."""
    if t["status"] in NON_TERMINAL_ALLOCATION_STATUSES:
        t["status"] = "EXHAUSTED" if t["consumed_cents"] >= t["allocated_cents"] else "ACTIVE"


def consume(t, amount_cents):
    t["consumed_cents"] += amount_cents
    reconcile_tranche(t)
    touch(t)


def release(t, amount_cents):
    """Releases floor consumed_cents at zero — consumption never goes negative."""
    t["consumed_cents"] = max(0, t["consumed_cents"] - amount_cents)
    reconcile_tranche(t)
    touch(t)


def aggregate_available(program):
    return program["aggregate_limit_cents"] - program["consumed_aggregate_cents"]
