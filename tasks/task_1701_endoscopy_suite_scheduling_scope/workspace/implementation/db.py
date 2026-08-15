"""In-memory data store. Fresh on every process boot (per-test-server isolation).

The store starts empty on every boot; no seeding of any kind occurs here.
"""

COLLECTIONS = [
    "patients",
    "providers",
    "procedure_types",
    "rooms",
    "anesthesia_providers",
    "scopes",
    "bookings",
    "scope_usages",
    "reprocessing_cycles",
    "culture_tests",
    "quarantine_cases",
    "specimens",
    "quality_reports",
    "anesthesia_assignments",
]

db = {name: {} for name in COLLECTIONS}

# Monotonic insertion counter; used as a deterministic tie-break wherever the
# spec orders by created_at ("ties broken by write order").
_seq_counter = [0]


def next_seq() -> int:
    _seq_counter[0] += 1
    return _seq_counter[0]
