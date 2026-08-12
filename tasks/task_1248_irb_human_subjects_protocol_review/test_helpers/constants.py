"""Domain thresholds and constants — numeric values named in PRD §2.4, §2.7, §3."""

# Logical clock (PRD §2.4)
DEFAULT_CLOCK_ISO = "2026-05-01T00:00:00Z"

# Review fee schedule (PRD §2.7): integer cents, round-half-up per line before summation.
BASE_FEE_CENTS = {
    "EXEMPT": 50000,
    "EXPEDITED": 150000,
    "FULL_BOARD": 250000,
}
RELIANCE_SITE_FEE_CENTS = 74999
INDUSTRY_MULTIPLIER = 1.5

# Compliance score ledger (PRD §3.8)
SCORE_BASE = 100
CONFIRMED_DEDUCTION = 20
OPEN_CASE_DEDUCTION = 5
LATE_UNFILED_DEDUCTION = 8
DEBARMENT_THRESHOLD = 60
SUBMISSION_GATE = 60

# Continuing review cadence (PRD §3.5, §3.7)
STANDARD_INTERVAL_DAYS = 365
HIGH_RISK_INTERVAL_DAYS = 180
CR_SUBMISSION_WINDOW_DAYS = 60

# Adverse-event filing windows in days (PRD §3.8)
AE_WINDOW_DAYS = {
    "SERIOUS_ADVERSE_EVENT": 5,
    "UNANTICIPATED_PROBLEM": 5,
    "PROTOCOL_DEVIATION_WITH_HARM": 15,
}

# Meetings and agenda (PRD §3.6)
MEETING_START_GRACE_MINUTES = 30
MAX_AGENDA_ITEMS = 8

# Reviewer assignments (PRD §3.4)
ASSIGNMENT_RESPONSE_WINDOW_DAYS = 7
MAX_ACTIVE_ASSIGNMENTS = 5
