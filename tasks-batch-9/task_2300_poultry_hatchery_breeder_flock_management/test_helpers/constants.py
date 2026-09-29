"""Domain constants for the Poultry Hatchery & Breeder Flock API.

Every value here is stated verbatim in the PRD; the module exists so that no
test hard-codes a magic threshold whose provenance is unclear.
"""

# ---------------------------------------------------------------------------
# Logical clock (PRD 2.4)
# ---------------------------------------------------------------------------

#: "Before any client sets it, the logical clock reads exactly
#: 2026-08-01T00:00:00Z, and it never falls back to wall-clock time."
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

# ---------------------------------------------------------------------------
# Pagination (PRD 2.3)
# ---------------------------------------------------------------------------

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
MIN_OFFSET = 0

# ---------------------------------------------------------------------------
# Settable-egg forecast (PRD 3.2)
# ---------------------------------------------------------------------------

#: "when the flock is younger than the first lighting step it sits on the base
#: photoperiod of 8.0 hours"
BASE_PHOTOPERIOD_HOURS = 8.0
#: "when no step applies yet the flock is fed the target ration of 160.0 grams
#: per hen per day"
TARGET_FEED_G = 160.0
#: "the settable ratio of 0.94 that expresses the share of eggs laid that grade
#: out as settable"
SETTABLE_RATIO = 0.94
#: "it is 0.95 whenever the flock's corrective_action_count is 1 or more, and
#: 1.0 when the count is 0"
CORRECTIVE_DERATE = 0.95
NO_DERATE = 1.0

#: lighting_factor: "Subtract eleven hours from photoperiod_hours ... Multiply
#: the result by 0.03 and add 0.70 ... cap it at 1.00."
LIGHTING_BASELINE_HOURS = 11.0
LIGHTING_SLOPE = 0.03
LIGHTING_INTERCEPT = 0.70
LIGHTING_FACTOR_CAP = 1.00

#: nutrition_factor: "clamp that ratio so it is never below 0.80 and never
#: above 1.10"
NUTRITION_FACTOR_MIN = 0.80
NUTRITION_FACTOR_MAX = 1.10

#: production_rate_pct age tiers (PRD 3.2)
PRODUCTION_RATE_BELOW_21 = 0.0
PRODUCTION_RATE_21_TO_24 = 45.0
PRODUCTION_RATE_25_TO_30 = 82.0
PRODUCTION_RATE_31_TO_45 = 74.0
PRODUCTION_RATE_46_PLUS = 61.0

# ---------------------------------------------------------------------------
# Age-of-egg (PRD 3.4)
# ---------------------------------------------------------------------------

#: "add a penalty of 0.75 effective days ... for each completed sanitation cycle"
SANITATION_AGE_PENALTY_DAYS = 0.75
#: "a storage_temp_c of exactly 18.0 is cool and earns the 1.0 factor, while
#: 18.01 is warm and earns 1.5"
STORAGE_TEMP_BOUNDARY_C = 18.0
WARM_FACTOR = 1.5
COOL_FACTOR = 1.0
UNSTORED_FACTOR = 2.0

# ---------------------------------------------------------------------------
# Hatch window derivation (PRD 3.5)
# ---------------------------------------------------------------------------

#: "subtract the free storage allowance of 3 days from weighted_age_days"
FREE_STORAGE_DAYS = 3
#: "one hour of incubation delay per day of excess storage"
HOUR_PER_STORAGE_DAY = 1.0
#: "pull_window_start_at is 6 hours before planned_pull_at and
#: pull_window_end_at is 6 hours after it"
PULL_WINDOW_EARLY_HOURS = 6
PULL_WINDOW_LATE_HOURS = 6
#: "a sanitation turnaround of 12 hours"
SETTER_TURNAROUND_HOURS = 12
#: "The lot's effective_age_days at the instant of the draw must not exceed the
#: maximum settable age of 10.00 effective days"
MAX_SETTABLE_AGE_DAYS = 10.00

# ---------------------------------------------------------------------------
# Environment monitoring (PRD 3.5)
# ---------------------------------------------------------------------------

#: "subtract the temperature tolerance of 0.30 degrees Celsius"
TEMP_TOLERANCE_C = 0.30
#: "strictly greater than the deviation-open threshold of 1.50 degree-hours"
DEVIATION_OPEN_THRESHOLD_DH = 1.50
#: "the uninterrupted run of within-tolerance segments ending at this reading
#: spans at least 2.0 hours"
DEVIATION_CLEAR_HOURS = 2.0

# ---------------------------------------------------------------------------
# Chick pull, quality score and processing (PRD 3.6, 3.7)
# ---------------------------------------------------------------------------

#: "hold_release_at is set to actual_pull_at advanced by the early hold of 4 hours"
EARLY_HOLD_HOURS = 4
#: "the standard box of 100 chicks"
BOX_SIZE = 100

#: vaccine_reject_rate four-band tier on the rounded preliminary_yield_pct
TIER_A_MIN_PCT = 96.0
TIER_B_MIN_PCT = 92.0
TIER_C_MIN_PCT = 85.0
TIER_A_RATE = 0.004
TIER_B_RATE = 0.008
TIER_C_RATE = 0.015
TIER_D_RATE = 0.028

#: quality score penalties
EARLY_PENALTY_PER_H = 1.80
LATE_PENALTY_PER_H = 2.40
DEG_HOUR_WEIGHT = 3.00
ENV_PENALTY_CAP = 25.00
CULL_WEIGHT = 0.90
FLAG_PENALTY = 4.00
QUALITY_SCORE_MAX = 100.00

# ---------------------------------------------------------------------------
# Placement, delivery and analytics (PRD 3.8, 3.9)
# ---------------------------------------------------------------------------

#: "the half-open interval that starts at the order's requested_placement_date
#: and ends 21 days later, excluding the end instant"
FARM_CYCLE_DAYS = 21
#: "the delivery tolerance of 2 days"
DELIVERY_TOLERANCE_DAYS = 2
#: "truncated to the 3 most recent entries"
ROLLING_WINDOW_SETS = 3
#: "strictly below the hatchability threshold of 82.0 percent"
HATCHABILITY_THRESHOLD_PCT = 82.0

# ---------------------------------------------------------------------------
# Tolerances used by assertions
# ---------------------------------------------------------------------------

#: Two-decimal-place quantities (percentages, ages, deviations, scores).
PCT_TOL = 0.005
#: Three-decimal-place quantities (degree-hours).
DEGREE_HOUR_TOL = 0.0005
#: Four-decimal-place quantities (factors, weighted_age_days).
FACTOR_TOL = 0.00005
#: One-decimal-place quantities (production_rate_pct, photoperiod, feed).
ONE_DP_TOL = 0.05
