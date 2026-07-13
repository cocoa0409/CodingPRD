"""Domain thresholds and numeric constants from the Vital Records PRD (§2, §3)."""

# Logical clock startup default (PRD §2.4)
CLOCK_STARTUP_DEFAULT = "2026-03-01T00:00:00Z"

# Statutory filing windows in days by event_type (PRD §3.1)
STATUTORY_WINDOW_DAYS = {
    "BIRTH": 10,
    "DEATH": 5,
    "FETAL_DEATH": 5,
}

# Late-registration surcharge (PRD §3.1)
DELAYED_BASE_FEE_CENTS = 2000
PER_DAY_SURCHARGE_CENTS = 100
MAX_SURCHARGE_CENTS = 5000

# Certified-copy fee schedule (PRD §3.6)
SEARCH_FEE_CENTS = 1500
ADDITIONAL_COPY_CENTS = 800
EXPEDITE_SURCHARGE_CENTS = 1900
INFORMATIONAL_COPY_CENTS = 1000

# Public-record aging thresholds in years by event_type (PRD §3.6)
PUBLIC_THRESHOLD_YEARS = {
    "BIRTH": 75,
    "DEATH": 25,
    "FETAL_DEATH": 25,
}

ELIGIBLE_RELATIONSHIPS = [
    "SELF", "PARENT", "CHILD", "SPOUSE", "SIBLING",
    "LEGAL_GUARDIAN", "LEGAL_REPRESENTATIVE",
]

# State remittance share (PRD §3.8)
STATE_SHARE_PCT = 0.45

# Temporal windows
RESCISSION_WINDOW_DAYS = 60          # PRD §3.5
EVIDENCE_THRESHOLD_DAYS = 365        # PRD §3.4
HEARING_BUFFER_MINUTES = 15          # PRD §3.3
