"""In-memory data store. Fresh on every process boot (per-test-server isolation)."""

COLLECTIONS = [
    "artists",
    "agreements",
    "rate_schedules",
    "income_events",
    "advances",
    "expenses",
    "approval_requests",
    "opportunities",
    "engagements",
    "options",
    "team_members",
    "statements",
    "statement_lines",
    "disputes",
    "audits",
]

db = {name: {} for name in COLLECTIONS}
