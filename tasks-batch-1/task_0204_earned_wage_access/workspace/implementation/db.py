"""In-memory data store.

Every collection is a plain dict keyed by id. The store starts EMPTY on every
boot; nothing is seeded. The test harness restarts the server (start.sh) before
every test, wiping all state.

PRD §2.4: most resources carry id (UUID, no prefix), created_at, updated_at,
version (starts at 1, increments on mutation). TimeEntry and Repayment are
write-once ledger rows carrying only id + created_at.
"""
import threading
import uuid

import clock
from timeutil import format_iso8601

# Collections keyed by id.
employers = {}
advance_policies = {}
fee_schedules = {}
pay_periods = {}
workers = {}
time_entries = {}
advances = {}
repayment_batches = {}
repayments = {}
reconciliation_statements = {}

# Monotonic ordinal so created_at-tie ordering is total & deterministic
# (multiple resources can share a pinned-clock created_at to the millisecond).
_seq_counter = 0
_lock = threading.RLock()


def reset():
    global _seq_counter
    employers.clear()
    advance_policies.clear()
    fee_schedules.clear()
    pay_periods.clear()
    workers.clear()
    time_entries.clear()
    advances.clear()
    repayment_batches.clear()
    repayments.clear()
    reconciliation_statements.clear()
    _seq_counter = 0


def new_id():
    return str(uuid.uuid4())


def next_seq():
    global _seq_counter
    with _lock:
        _seq_counter += 1
        return _seq_counter


def new_common_fields():
    """id, created_at, updated_at, version for full (common_fields: true) entities."""
    ts = format_iso8601(clock.now())
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }


def new_ledger_fields():
    """id, created_at for light (common_fields: false) entities (TimeEntry, Repayment)."""
    ts = format_iso8601(clock.now())
    return {
        "id": new_id(),
        "created_at": ts,
        "_seq": next_seq(),
    }


def touch(entity):
    """Refresh updated_at and bump version (a mutation, per PRD §2.4)."""
    entity["updated_at"] = format_iso8601(clock.now())
    entity["version"] = entity.get("version", 1) + 1
