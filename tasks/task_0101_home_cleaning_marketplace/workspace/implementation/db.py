"""In-memory data store.

All state lives in module-level dicts keyed by id. Nothing is seeded — the
store starts empty on every process boot (per-test-server isolation wipes
state by re-launching the process). Tests build all preconditions via the
declared API surface.

Common fields per PRD §2.4:
  - id: UUID, no type prefix
  - created_at: ISO8601 UTC, 3 fractional digits
  - updated_at: refreshed on every mutation (absent for append-only records)
  - version: starts at 1, +1 on every mutation (absent for append-only records)

Tip and LedgerEntry are append-only: only id + created_at (no updated_at,
no version).
"""
from datetime import datetime, timezone

from util import new_uuid

# Collections (entity name -> {id: record dict}).
customers = {}
addresses = {}
cleaners = {}
background_checks = {}
pricing_plans = {}
booking_series = {}
bookings = {}
preferred_pros = {}
tips = {}
cleaner_payouts = {}
ledger_entries = {}

COLLECTIONS = {
    "Customer": customers,
    "Address": addresses,
    "Cleaner": cleaners,
    "BackgroundCheck": background_checks,
    "PricingPlan": pricing_plans,
    "BookingSeries": booking_series,
    "Booking": bookings,
    "PreferredPro": preferred_pros,
    "Tip": tips,
    "CleanerPayout": cleaner_payouts,
    "LedgerEntry": ledger_entries,
}

# Monotonic sequence so created_at ties (same clock instant) still sort
# deterministically in insertion order for list endpoints and tie-breaks.
_seq = 0


def next_seq():
    global _seq
    _seq += 1
    return _seq


def _now():
    return datetime.now(timezone.utc)


def insert(collection, record, append_only=False):
    """Insert a new record, stamping system common fields.

    append_only=True for Tip and LedgerEntry: only id + created_at.
    """
    rid = new_uuid()
    now = _now()
    record["id"] = rid
    record["created_at"] = now
    record["_seq"] = next_seq()
    if not append_only:
        record["updated_at"] = now
        record["version"] = 1
    collection[rid] = record
    return record


def touch(record):
    """Mutate bookkeeping: bump version and updated_at on a versioned record."""
    record["version"] = record.get("version", 1) + 1
    record["updated_at"] = _now()
    return record
