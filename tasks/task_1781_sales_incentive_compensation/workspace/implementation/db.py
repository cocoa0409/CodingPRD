"""In-memory data store. Fresh on every process boot (per-test-server isolation)."""

COLLECTIONS = [
    "programs",
    "plans",
    "reps",
    "assignments",
    "transactions",
    "credit_entries",
    "adjustments",
    "disputes",
    "statements",
    "payroll_exports",
]

db = {name: {} for name in COLLECTIONS}
