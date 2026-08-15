"""In-memory data store. Fresh on every process boot (per-test-server isolation).

The store starts EMPTY at startup: no seeding, no preloading — every entity is
constructed through the declared API surface by the tests themselves.
"""
import itertools

COLLECTIONS = [
    "suppliers",
    "documents",
    "shipments",
    "units",
    "freezers",
    "readings",
    "excursions",
    "cases",
    "reservations",
    "recalls",
    "adverse_reactions",
    "policies",
    "dispositions",
]

db = {name: {} for name in COLLECTIONS}

# Global monotonic insertion sequence — deterministic tie-break for sorts that
# would otherwise rely on id ordering, and verification ordering for documents.
_seq = itertools.count(1)


def next_seq() -> int:
    return next(_seq)
