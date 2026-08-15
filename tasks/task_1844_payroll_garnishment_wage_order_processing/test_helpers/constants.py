"""Domain thresholds and numeric constants from the PRD calculations (§2.4, §3.4, §3.6)."""

# Logical clock startup default (PRD §2.4): the pinned startup instant.
CLOCK_START = "2026-08-01T00:00:00Z"

# Withholding waterfall constants (PRD §3.6).
FEDERAL_MINIMUM_WAGE_CENTS = 725
PERIOD_WEEKS = {
    "WEEKLY": 1,
    "BIWEEKLY": 2,
    "SEMIMONTHLY": 2.1667,
    "MONTHLY": 4.3333,
}

# Deadlines and limits (PRD §3.3, §3.4).
ANSWER_SLA_DAYS = 10
NOTIFICATION_SLA_DAYS = 7
MAX_SUSPENSIONS = 3

# Remittance timing offsets in business days (PRD §3.7).
REMITTANCE_TIMING_OFFSETS = {
    "SAME_DAY": 0,
    "NEXT_BUSINESS_DAY": 1,
    "THREE_BUSINESS_DAYS": 3,
}

# California-style default caps used throughout the test fixtures (PRD §3.1).
DEFAULT_CAPS = {
    "CHILD_SUPPORT": 0.50,
    "FEDERAL_TAX_LEVY": 0.65,
    "STUDENT_LOAN": 0.15,
    "CREDITOR": 0.25,
}

# Standard semi-monthly period used by most fixtures.
PERIOD_START = "2026-08-01"
PERIOD_END = "2026-08-15"
PAY_DATE = "2026-08-15"
