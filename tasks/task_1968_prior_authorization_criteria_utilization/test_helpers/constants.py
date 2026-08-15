"""Domain thresholds — numeric constants from the PRD (§2.5, §3.4, §3.6, §3.7)."""

# Startup logical clock (PRD §2.5).
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

# Turnaround SLA matrix in hours, keyed by (urgency, line_of_business) (PRD §2.5).
SLA_HOURS = {
    ("URGENT", "MEDICARE"): 24,
    ("URGENT", "MEDICAID"): 24,
    ("URGENT", "COMMERCIAL"): 48,
    ("STANDARD", "MEDICARE"): 72,
    ("STANDARD", "MEDICAID"): 120,
    ("STANDARD", "COMMERCIAL"): 168,
}
APPEAL_SLA_HOURS = 720  # 30-day appeal SLA (PRD §2.5)

# Provider statistics (PRD §3.6).
ROLLING_WINDOW_HOURS = 2160  # 90 days
GOLD_CARD_MIN_COUNT = 10
GOLD_CARD_MIN_RATE = 0.90

# Delegation oversight (PRD §3.7).
DELEGATION_SUSPEND_THRESHOLD = 3

# Determination notice template (PRD §3.4).
APPEAL_WINDOW_HOURS = 4320  # 180 days

TEST_DEFAULTS = {
    "SERVICE_CATEGORY": "IMAGING",
    "SERVICE_CODE": "72148",
    "LINE_OF_BUSINESS": "COMMERCIAL",
    "CRITERIA_SET_NAME": "Spine Imaging Criteria",
    "VERSION_LABEL": "1.0",
    "EFFECTIVE_FROM": "2026-01-01T00:00:00Z",
}
