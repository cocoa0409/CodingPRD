"""In-memory data store. Fresh on every process boot (per-test-server isolation).

No seeding: every collection starts empty; tests build all state via the API.
"""

COLLECTIONS = [
    "portfolios",
    "leases",
    "contacts",
    "options",
    "assessments",
    "arbitrations",
    "notices",
    "reminders",
    "amendments",
    "ledger",
    "clock_events",
]

db = {name: {} for name in COLLECTIONS}
