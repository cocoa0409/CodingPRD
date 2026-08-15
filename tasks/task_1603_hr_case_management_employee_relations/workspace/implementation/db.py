"""In-memory data store. Fresh on every process boot (per-test-server isolation).

The store starts completely empty — no seeding. Every entity is constructed
through the declared API surface by the caller.
"""

COLLECTIONS = [
    "employees",
    "investigators",
    "intake_channels",
    "holidays",
    "cases",
    "interviews",
    "evidence_items",
    "credibility_assessments",
    "findings",
    "recommended_actions",
    "closure_notices",
    "trend_snapshots",
    "litigation_packages",
]

db = {name: {} for name in COLLECTIONS}

# Server-minted sequences (never reused, never compacted).
case_number_seq = {}   # calendar year (int) -> last assigned sequence (int)
custody_seq = {}       # case_id -> last assigned custody_sequence (int)

_insertion_seq = [0]   # global monotonic insertion counter (deterministic ordering)


def next_insertion_seq() -> int:
    _insertion_seq[0] += 1
    return _insertion_seq[0]
