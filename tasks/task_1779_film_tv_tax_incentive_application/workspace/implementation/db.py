"""In-memory data store. Fresh on every process boot (per-test-server isolation).

No seeding: every entity is created through the declared API surface.
"""

COLLECTIONS = [
    "jurisdiction_programs",
    "production_companies",
    "productions",
    "credit_buyers",
    "applications",
    "vendors",
    "spend_entries",
    "audit_packages",
    "certificates",
    "transfers",
    "clawback_cases",
]

db = {name: {} for name in COLLECTIONS}

# Monotonic insertion sequence for stable created_at tie-breaking.
_seq = {"n": 0}


def next_seq() -> int:
    _seq["n"] += 1
    return _seq["n"]
