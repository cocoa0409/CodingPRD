"""Domain thresholds and numeric constants from PRD calculations."""

# Per-visit amortization: average visits per month by visit_frequency (PRD §3.4).
AVG_VISITS_PER_MONTH = {
    "WEEKLY": 4.33,
    "BIWEEKLY": 2.17,
    "TWICE_WEEKLY": 8.67,
    "DAILY": 30,
}

# Bundle discount applied to the sum of SANITIZE+DEODORIZE when both are present
# on the same visit (PRD §3.4).
BUNDLE_SANITIZE_DEODORIZE_DISCOUNT_BP = 1500

# Multifamily pricing uses basis points where 10000 == 1.00x (PRD §3.4).
MULTIFAMILY_BASE_BP = 10000

# Route load: a fully-loaded route is 10000 basis points (PRD §2.8).
FULL_LOAD_BP = 10000

# Satisfaction: exponential decay per day and RESOLVED-report reset (PRD §3.8).
SATISFACTION_DECAY_PER_DAY = 0.9
SATISFACTION_RESOLVED_RESET_RATING = 5.0

# Satisfaction resolution credit cap (PRD §2.9 validation 19).
MAX_RESOLUTION_CREDIT_CENTS = 100000

# Logical clock default at server startup (PRD §2.6).
LOGICAL_CLOCK_DEFAULT_ISO = "2026-05-01T00:00:00Z"

# Common test phone prefix
DEFAULT_PHONE = "+14155550100"
DEFAULT_REGION = "R1"
