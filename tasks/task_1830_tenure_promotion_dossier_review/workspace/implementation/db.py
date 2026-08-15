"""In-memory data store. Fresh on every process boot (per-test-server isolation).

The store starts empty on every boot — no seeding. Every entity a test needs
is constructed via the declared API surface.
"""

COLLECTIONS = [
    "candidates",
    "cases",
    "dossier_items",
    "reviewers",
    "invitations",
    "committees",
    "members",
    "rounds",
    "votes",
    "clock_extensions",
    "midterm_reviews",
    "decisions",
    "appeals",
]

db = {name: {} for name in COLLECTIONS}

# Monotonic insertion counter — stable tiebreak for created_at-ascending sorts
# (the logical clock can stand still across many creations).
_seq = {"n": 0}


def next_seq() -> int:
    _seq["n"] += 1
    return _seq["n"]
