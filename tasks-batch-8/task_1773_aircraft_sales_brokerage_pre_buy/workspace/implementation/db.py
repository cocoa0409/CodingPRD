"""In-memory data store. Fresh and empty on every process boot.

The store MUST NOT be seeded: every entity a test needs is built through the
declared API surface. Per-test-server isolation re-launches this process
before every test, so module-level state resets naturally.
"""
import itertools

COLLECTIONS = [
    "facilities",
    "listings",
    "buyers",
    "comps",
    "lois",
    "transactions",
    "escrows",
    "bookings",
    "discrepancies",
]

db = {name: {} for name in COLLECTIONS}

_seq = itertools.count(1)


def next_seq() -> int:
    """Monotonic insertion sequence; orders list results (created_at asc)."""
    return next(_seq)
