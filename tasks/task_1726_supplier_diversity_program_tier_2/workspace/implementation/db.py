"""In-memory data store. Fresh on every process boot (per-test-server isolation).

The store starts empty on every boot; no seeding of any kind occurs here.
"""

COLLECTIONS = [
    "business_units",
    "suppliers",
    "certifications",
    "spend_records",
    "tier2_reports",
    "goals",
    "scorecards",
    "sourcing_events",
    "invitations",
    "engagements",
    "audit_cases",
]

db = {name: {} for name in COLLECTIONS}

# Monotonic insertion counter; deterministic tie-break wherever the spec
# orders by created_at (ties broken by write order).
_seq_counter = [0]


def next_seq() -> int:
    _seq_counter[0] += 1
    return _seq_counter[0]
