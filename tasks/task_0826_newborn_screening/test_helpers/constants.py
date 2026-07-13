"""Domain thresholds — numeric constants from the Newborn Screening PRD calculations."""

# Logical clock startup default (PRD §2.5)
CLOCK_STARTUP_DEFAULT = "2026-03-01T00:00:00Z"

# Specimen timeliness (PRD §2.9, §3.9)
MIN_COLLECTION_AGE_HOURS = 24
MAX_COLLECTION_AGE_HOURS = 48
MAX_TRANSIT_ONTIME_HOURS = 24
MAX_REPORT_TURNAROUND_HOURS = 120

# Specimen acceptability (PRD §3.3)
REQUIRED_SPOTS = 4
TERM_WEEKS = 37
MAX_TRANSIT_HOURS = 96

# CCHD interpretation (PRD §3.4)
CCHD_FAIL_BELOW = 90
CCHD_PASS_AT = 95
CCHD_DIFF_MAX = 3

# Follow-up priority scoring (PRD §3.5)
W_CRITICAL = 50
W_PRETERM = 20
W_LOWBIRTH = 15
W_CONFIRMED = 40
W_REPEAT_NORMAL = 30
PRETERM_WEEKS = 34
LOW_BIRTH_WEIGHT_GRAMS = 1500

# Windows (PRD §3.3, §3.5)
RECOLLECTION_WINDOW_DAYS = 30
REPEAT_WINDOW_DAYS = 30

# Assay instrument exclusivity buffer (PRD §3.7)
ASSAY_BUFFER_MINUTES = 30
