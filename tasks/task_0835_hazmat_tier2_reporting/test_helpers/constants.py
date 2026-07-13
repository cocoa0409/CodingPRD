"""Domain thresholds — numeric constants from the PRD calculations (§2.8, §3.3, §3.4, §3.7)."""

# Threshold determination (§3.3)
NON_EHS_THRESHOLD_LBS = 10000
EHS_TPQ_CAP_LBS = 500

# Hazard index (§3.3)
LBS_PER_UNIT = 1000

# Tier II filing fee (§3.4)
BASE_FEE_CENTS = 5000
PROVISIONAL_RATE_CENTS = 2000
INCLUDED_CHEMICALS = 5
TIER1_MAX = 25
TIER1_RATE_CENTS = 2000
TIER2_RATE_CENTS = 1000
EHS_SURCHARGE_CENTS = 5000
LATE_PENALTY_PCT = 0.10

# Inspector scheduling buffer (§3.6)
MIN_INSPECTION_GAP_HOURS = 24

# Risk-management plan (§3.7)
RMP_RESUBMIT_YEARS = 5
RMP_DUE_WINDOW_DAYS = 90

# Logical clock startup default (§2.5)
CLOCK_DEFAULT_UTC = "2026-03-01T00:00:00Z"

# A syntactically valid UUID that is guaranteed absent from an empty DB.
NON_EXISTENT_UUID = "00000000-0000-4000-8000-000000000000"
