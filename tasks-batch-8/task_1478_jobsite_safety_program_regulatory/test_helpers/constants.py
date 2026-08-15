"""Domain thresholds — numeric constants from the PRD (§2.5, §3.4, §3.5, §3.6, §3.7, §3.8)."""

# Logical clock (PRD §2.5): startup default before any set call.
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"
# Conventional test clock used by most setups.
CLOCK_START = "2026-08-01T08:00:00Z"

# Deficiency severity SLA in days (PRD §3.5).
DEFICIENCY_SLA_DAYS = {
    "MINOR": 14,
    "MAJOR": 7,
    "CRITICAL": 3,
    "IMMINENT_DANGER": 0,
}

# Compliance score model (PRD §3.7).
SCORE_BASE = 100
SEVERITY_DEDUCTION = {
    "MINOR": 5,
    "MAJOR": 15,
    "CRITICAL": 30,
    "IMMINENT_DANGER": 50,
}
RECORDABLE_INCIDENT_DEDUCTION = 25
DEMOTE_THRESHOLD = 80

# Permit conflict rules (PRD §3.4).
HOT_WORK_BUFFER_MINUTES = 60

# Post-incident drug test window (PRD §3.8).
POST_INCIDENT_WINDOW_HOURS = 32

# OSHA rate normalization (PRD §3.6).
OSHA_BASE_HOURS = 200000

# Posture rule (PRD §2.6): >=3 overdue deficiencies of any severity -> RESTRICTED.
RESTRICTED_OVERDUE_COUNT = 3

# Common test timestamps.
CERT_ISSUED = "2026-07-01"
CERT_EXPIRES = "2027-07-01"
PLAN_EFFECTIVE = "2026-08-01"
HUDDLE_DATE = "2026-08-01"
