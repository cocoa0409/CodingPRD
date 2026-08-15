"""In-memory data store. Fresh on every process boot (per-test-server isolation).

Storage is Python dicts keyed by id only — no SQLite, no JSON dump, no /tmp
cache, no external persistence, and nothing is seeded at startup.
"""

COLLECTIONS = [
    "high_schools",
    "terms",
    "students",
    "courses",
    "prerequisites",
    "placement_records",
    "instructors",
    "credential_applications",
    "offerings",
    "enrollments",
    "transcript_entries",
    "funding_agreements",
    "invoices",
    "payments",
    "articulation_agreements",
]

db = {name: {} for name in COLLECTIONS}

# Monotonic insertion sequence used as a deterministic tiebreak after created_at.
_seq = [0]


def next_seq() -> int:
    _seq[0] += 1
    return _seq[0]
