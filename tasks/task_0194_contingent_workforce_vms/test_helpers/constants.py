"""Domain thresholds — numeric constants from PRD calculations (§3)."""

# Per-category expense reimbursement caps in cents (PRD §3.9).
EXPENSE_CAP_CENTS = {
    "TRAVEL": 50000,
    "LODGING": 30000,
    "MEALS": 7500,
    "EQUIPMENT": 100000,
    "OTHER": 20000,
}

# Overtime multiplier for timesheet amounts (PRD §3.8).
OT_MULTIPLIER = 1.5

# Negotiation rounds cap (PRD §3.3).
MAX_NEGOTIATION_ROUNDS = 5

# Default timesheet approval window in days (PRD §3.1).
DEFAULT_TIMESHEET_APPROVAL_WINDOW_DAYS = 7

# Default tier release interval in hours (PRD §3.2).
DEFAULT_TIER_RELEASE_INTERVAL_HOURS = 24

# Program clock epoch on creation (PRD §2.4).
CLOCK_EPOCH = "1970-01-01T00:00:00.000Z"

TEST_DEFAULTS = {
    "DEFAULT_MARKUP_PCT": 0.45,
    "MAX_MARKUP_PCT": 0.60,
    "TENURE_LIMIT_DAYS": 180,
    "TENURE_WARNING_DAYS": 120,
    "MAX_PAY_RATE_CENTS": 20000,
    "PAY_RATE_CENTS": 8000,
}
