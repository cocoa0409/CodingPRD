"""In-memory data store. Fresh on every process boot (per-test-server isolation).

No seeding: every entity is created through the declared API surface.
"""

COLLECTIONS = [
    "groups",
    "segments",
    "agreements",
    "events",
    "waivers",
    "depots",
    "supplies",
    "debris_reports",
    "hazards",
    "signs",
]

db = {name: {} for name in COLLECTIONS}

# Monotonic insertion sequence for stable created_at-tiebreaking on list sorts.
_seq = [0]


def next_seq() -> int:
    _seq[0] += 1
    return _seq[0]
