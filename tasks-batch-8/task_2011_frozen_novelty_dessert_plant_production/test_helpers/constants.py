"""Domain thresholds — numeric constants from PRD calculations (§2.5, §3)."""

# Logical clock startup default (PRD §2.7).
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

# Mix costing (PRD §3.6).
MIX_COST_CENTS_PER_LITRE = 85

# Mix pasteurization shelf life in hours (PRD §3.3).
MIX_SHELF_HOURS = 72

# Changeover matrix durations in minutes (PRD §3.4).
RINSE_MINUTES = 30
WASH_MINUTES = 90
ALLERGEN_CIP_MINUTES = 240

# Tunnel booking trailing cleanup buffer in minutes (PRD §3.5).
TUNNEL_BUFFER_MINUTES = 30

# Temperature replay thresholds (PRD §3.9).
ABUSE_THRESHOLD_C = -18.0
HEAT_SHOCK_THRESHOLD_C = -12.0

# Claim payout constants (PRD §3.9).
STANDARD_FREE_MINUTES = 30
STANDARD_LOW_TIER_MAX_MINUTES = 120
STANDARD_RATE_LOW_CENTS_PER_MIN = 200
STANDARD_RATE_HIGH_CENTS_PER_MIN = 350
CARRIER_RATE_CENTS_PER_MIN = 150
CARRIER_DEDUCTIBLE_CENTS = 5000
CARRIER_CAP_PCT = 0.80

# Claim appeal window in days (PRD §3.9).
APPEAL_WINDOW_DAYS = 14

# Contract fulfillment tiers (PRD §3.2).
TIER_HIGH_MIN_PCT = 90
TIER_MID_MIN_PCT = 50
RATE_HIGH = 0.10
RATE_MID = 0.20
RATE_LOW = 0.35

# Heat-shock ice-crystal limits by product format, in microns (PRD §3.10).
HEAT_SHOCK_LIMIT_UM_NOVELTY = 120
HEAT_SHOCK_LIMIT_UM_BULK = 150

# Complaint lab cycle cap (PRD §3.10).
LAB_CYCLE_CAP = 3

# Build plan shelf-life buffer in days (PRD §3.11).
MIN_REMAINING_SHELF_DAYS = 30
