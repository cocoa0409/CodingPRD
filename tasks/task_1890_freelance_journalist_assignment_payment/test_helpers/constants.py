"""Domain thresholds — numeric constants from PRD section 3 (DeskConfig defaults)."""

# Logical clock (PRD section 2.5)
DEFAULT_START_CLOCK = "2026-08-01T00:00:00Z"
DEFAULT_DEADLINE = "2026-08-10T00:00:00Z"

# Kill fee policy (PRD section 3.4)
PRE_DELIVERY_KILL_PCT = 25
DEFAULT_POST_DELIVERY_KILL_PCT = 50
LATE_KILL_DIVISOR = 2

# Expense policy (PRD section 3.7)
RECEIPT_REQUIRED_CENTS = 2500
CATEGORY_CAPS_CENTS = {
    "TRAVEL": 50000,
    "MEALS": 7500,
    "EQUIPMENT": 20000,
    "OTHER": 5000,
}

# Invoice / payment terms (PRD sections 3.8-3.9)
NET_TERMS_DAYS = 30
LATE_FEE_DAILY_BPS = 50

# Tax / withholding (PRD section 3.8)
REPORTING_THRESHOLD_CENTS = 60000
BACKUP_WITHHOLDING_BPS = 2400
FOREIGN_STATUTORY_BPS = 3000
TREATY_RATES_BPS = {"GB": 0, "DE": 0, "JP": 1000, "IN": 1500, "BR": 1500}
DOC_VALIDITY_DAYS = 1095
BPS_DENOMINATOR = 10000

# Verification thresholds (PRD section 3.5)
FLAG_THRESHOLD_BPS = 2000
AI_FLAG_THRESHOLD_BPS = 7000

# Rights (PRD section 3.6)
REUSE_ROYALTY_PCT = 25
ALL_RIGHTS_UPLIFT_PCT = 35

# Test-side user identifiers for opaque roles (PRD section 2.1)
FIN_USER_1 = "fin-1"
FIN_USER_2 = "fin-2"
VE_RECORDER = "ve-recorder"
VE_ADJUDICATOR = "ve-adjudicator"
