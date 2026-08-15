"""Domain thresholds — numeric constants from PRD calculation rules (§3)."""

# Fixed logical clock at server startup (PRD §2.8)
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

# Market screening (PRD §3.1)
QUALIFY_MIN_SCORE = 60.00
TIER_A_MIN_SCORE = 75.00
TIER_B_MIN_SCORE = 50.00
TIER_A_BONUS = 4
TIER_B_BONUS = 2
PENETRATION_PENALTY_MAX = 20

# Site visit gate (PRD §3.4)
VISIT_PASS_MIN = 70.00

# Occupancy bands (PRD §3.5)
BAND_GREEN_MAX_BP = 1500
BAND_YELLOW_MAX_BP = 2200

# Cannibalization cap at forecast lock: 25% of gross (PRD §3.5)
CANNIBALIZATION_CAP_BP = 2500

# Committee tally (PRD §3.6)
APPROVE_PCT_STRICT = 60
QUORUM_NUM = 2
QUORUM_DEN = 3

# Budget cap at submit-committee: 90% of annual capex budget (PRD §3.6)
BUDGET_CAP_BP = 9000

# Lease drift ceiling at execute: agreed rent x 1.05 (PRD §3.8)
LEASE_DRIFT_CAP_BP = 10500

# Crew build-window buffer (PRD §3.8): conflict iff new_start <= other_end + 6 days
CREW_BUFFER_GAP_DAYS = 7

# Performance variance (PRD §3.9)
MISS_THRESHOLD_BP = -2000
UNDERPERFORMING_MISSES = 2
PERIODS_PER_YEAR = 12

# Format square-footage bands at run-screening (PRD §3.2)
FORMAT_SQFT_BANDS = {
    "EXPRESS": (2000, 4000),
    "STANDARD": (8000, 15000),
    "FLAGSHIP": (20000, 45000),
}

# ANALOG format factors (PRD §3.5)
FORMAT_FACTORS = {
    "EXPRESS": 0.85,
    "STANDARD": 1.00,
    "FLAGSHIP": 1.20,
}

# Standard review deadline used across fixtures (strictly after the default clock)
REVIEW_DEADLINE = "2026-08-15T00:00:00Z"
