"""Domain thresholds and money constants named by the PRD."""

# Logical clock startup default (PRD §2.4): before any client advances it,
# the logical clock reads exactly this instant.
CLOCK_START_ISO = "2026-08-01T00:00:00Z"

# Eligibility posture bands (PRD §3.2): inclusive-lower boundaries.
ISS_CONDITIONAL_FLOOR = 50
ISS_INELIGIBLE_FLOOR = 75

# Weight clearance (PRD §3.5 check 11): allowance of five percent of the
# vehicle's gvwr_lbs — 500 basis points, computed in whole pounds.
WIM_TOLERANCE_BPS = 500

# Subscription billing tiers (PRD §3.8).
TIER_1_RATE_CENTS = 1799
TIER_2_RATE_CENTS = 1599
TIER_3_RATE_CENTS = 1399
TIER_1_MAX_LINES = 10
TIER_2_MAX_LINES = 50
PILOT_SURCHARGE_CENTS = 200
NET_TERMS_DAYS = 14

# ROI reporting (PRD §3.8).
AVOIDED_COST_PER_BYPASS_CENTS = 1275

# Dispute filing window (PRD §3.6): the difference between today and the
# approach's calendar date may not exceed 30 days.
DISPUTE_WINDOW_DAYS = 30

# Dispute credit bounds (PRD §3.6).
CREDIT_MIN_CENTS = 1
CREDIT_MAX_CENTS = 100000

# Feed timeliness (PRD §3.5): approaches older than 48h before now are late.
STALE_APPROACH_HOURS = 48

# Common fixture values.
DEFAULT_GVWR_LBS = 80000
# 80000 + floor(80000 * 500 / 10000) — the weight clearance limit for the
# default vehicle.
DEFAULT_WEIGHT_LIMIT_LBS = 84000
DEFAULT_CREDENTIAL_SETS = ["IFTA", "IRP", "UCR"]
DEFAULT_SUB_START = "2026-08-01"
DEFAULT_SUB_END = "2026-12-31"

# Period used by the bulk of the billing scenarios.
PERIOD_YEAR = 2026
PERIOD_MONTH = 8
DAYS_IN_PERIOD = 31
DEFAULT_DUE_DATE = "2026-09-15"
