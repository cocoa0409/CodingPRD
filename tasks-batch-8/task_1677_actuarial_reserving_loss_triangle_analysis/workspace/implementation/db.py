"""In-memory data store. Fresh on every process boot (per-test-server isolation)."""

COLLECTIONS = [
    "segments",
    "catastrophe_events",
    "claims",
    "claim_transactions",
    "triangles",
    "development_patterns",
    "reserve_runs",
    "studies",
    "opinions",
    "roll_forwards",
]

db = {name: {} for name in COLLECTIONS}

# Monotonic insertion counter used to give every record a stable created-order
# ordinal so list endpoints can sort by creation timestamp ascending even when
# two records land within the same millisecond.
_seq_counter = {"n": 0}


def next_seq() -> int:
    _seq_counter["n"] += 1
    return _seq_counter["n"]
