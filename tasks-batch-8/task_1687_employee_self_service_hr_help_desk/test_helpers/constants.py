"""Domain thresholds and logical-clock constants from the PRD."""

# Logical clock (PRD §2.5): startup default before any explicit set.
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"

# SLA clock evaluation (PRD §3.6): inclusive at-risk fraction.
SLA_AT_RISK_FRACTION = 0.75

# Ticket lifecycle constants (PRD §3.5).
REOPEN_WINDOW_HOURS = 72
AUTO_CLOSE_DAYS = 5

# Survey validity (PRD §3.8): expires_at = issued_at + 7 days.
SURVEY_TTL_DAYS = 7

# Fraud verification (PRD §3.7).
FRAUD_MAX_ATTEMPTS = 3
FRAUD_LOOKBACK_DAYS = 30

# CSAT rolling calculation (PRD §3.8).
CSAT_WINDOW_DAYS = 30
CSAT_HALF_LIFE_DAYS = 14
CSAT_MIN_SURVEYS = 3
CSAT_COACHING_THRESHOLD = 3.00

# Staffing coverage posture (PRD §3.9).
COVERAGE_UNDER_RATIO = 0.90
COVERAGE_SURPLUS_RATIO = 1.10

# Deflection linkage (PRD §3.4) and rate metric (PRD §3.6).
DEFLECTION_WINDOW_MINUTES = 60
DEFLECTION_WINDOW_DAYS = 30

# Business-hours calendar (PRD §2.8).
BUSINESS_DAY_START_UTC = "09:00"
BUSINESS_DAY_END_UTC = "17:00"

# Confidentiality masking placeholder (PRD §2.7).
MASKED_PLACEHOLDER = "[REDACTED]"
