"""In-memory data store. Fresh on every process boot (per-test-server isolation)."""

COLLECTIONS = [
    "zones",
    "admissions",
    "lots",
    "manipulation_orders",
    "withdrawals",
    "weekly_entries",
    "annual_reconciliations",
    "access_badges",
    "access_events",
]

db = {name: {} for name in COLLECTIONS}
