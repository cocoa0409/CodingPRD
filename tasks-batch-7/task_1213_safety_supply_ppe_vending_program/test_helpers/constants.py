"""Domain thresholds and numeric constants from PRD §3."""

# Chargeback admin fee: 2.5% per line, round-half-up per line before summation (PRD §3.7)
ADMIN_FEE_BPS = 250

# Fit-test validity: PASS -> expires_on = tested_on + 365 days (PRD §3.2)
FIT_TEST_VALIDITY_DAYS = 365

# Serialized unit overdue grace: quarantine lands at next_inspection_due_on + 31 days (PRD §3.8)
OVERDUE_GRACE_DAYS = 30

# Logical clock default before any set (PRD §2.4)
CLOCK_START_ISO = "2026-05-01T00:00:00Z"
