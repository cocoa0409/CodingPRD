"""In-memory data store. Fresh on every process boot (per-test-server isolation).

No seeding, no disk persistence: every entity is created via the API surface.
"""

COLLECTIONS = [
    "syndications",
    "investors",
    "properties",
    "offerings",
    "subscriptions",
    "documents",
    "capital_calls",
    "contributions",
    "quarterly_reports",
    "distributions",
    "distribution_lines",
    "capital_events",
    "k1_packages",
    "transfer_requests",
    "portal_sessions",
]

db = {name: {} for name in COLLECTIONS}

_seq = {"n": 0}


def next_seq() -> int:
    """Monotonic insertion counter — stable tie-break after created_at."""
    _seq["n"] += 1
    return _seq["n"]
