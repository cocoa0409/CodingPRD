"""In-memory data store. Fresh on every process boot (per-test-server isolation).

The store starts empty on every boot — no seeding. Every entity a test needs is
constructed through the declared API surface.
"""

COLLECTIONS = [
    "growers",
    "blocks",
    "lots",
    "ca_rooms",
    "allocations",
    "inspections",
    "specs",
    "packing_runs",
    "pools",
    "settlements",
]

db = {name: {} for name in COLLECTIONS}

# Monotonic insertion sequence; stable tiebreak for created_at ordering and the
# selector's created_at tiebreak (identical logical-clock stamps).
_seq = 0


def next_seq() -> int:
    global _seq
    _seq += 1
    return _seq
