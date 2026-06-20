"""Domain thresholds — numeric constants from PRD calculations."""

# Read validation high-reading band (PRD §3.5)
HIGH_READING_MULTIPLE = 3

# Statement schedule windows (PRD §3.8, §3.10, §3.11)
NET_DAYS = 21               # statement due 21 days after issue
GRACE_DAYS = 5              # late fee only after due_date + 5 (strict >)
COLLECTIONS_GRACE_DAYS = 30  # collections only at/after due_date + 30 (>=)
MAX_REOPENS = 2             # a dispute may be reopened at most twice

# Late-fee ladder (PRD §3.10)
LATE_FEE_PCT = 0.05
LATE_FEE_FLAT_CENTS = 500
LATE_FEE_MAX_CENTS = 5000
LATE_FEE_MAX_PCT = 0.10

# Property percentage defaults (PRD §2.7, §3.1)
DEFAULT_RECOVERY_CAP_PCT = 0.85
DEFAULT_COMMON_AREA_PCT = 0.10

TEST_DEFAULTS = {
    "STATE_CODE": "CA",
    "PERIOD_LABEL": "2026-06",
    "PERIOD_START": "2026-06-01T00:00:00Z",
    "PERIOD_END": "2026-06-30T00:00:00Z",
    "MOVE_IN_DATE": "2026-06-01T00:00:00Z",
}
