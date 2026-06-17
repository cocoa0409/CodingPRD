"""Domain thresholds — numeric constants from the PRD pricing & risk rules."""

# Waste factor (PRD §3.3): category base, seam allowance, big-area surcharge.
WASTE_BASE = {
    "HARDWOOD": 10.0,
    "LVP": 8.0,
    "TILE": 12.0,
    "CARPET": 5.0,
}
SEAM_PER_ROOM_PCT = 1.0
SEAM_CAP_PCT = 6.0
BIG_AREA_THRESHOLD_SQFT = 600          # strict >: exactly 600 does NOT trigger
BIG_AREA_SURCHARGE_PCT = 3.0

# Estimate totals (PRD §3.5): tear-out/haul-away labor rate.
TEAR_OUT_LABOR_CENTS_PER_SQFT = 150

# Ready date (PRD §3.6 / §3.7).
SECONDS_PER_DAY = 86400

# Warranty risk (PRD §3.9): additive components, clamped to [0, 100].
WARRANTY_BASE = {
    "HARDWOOD": 30,
    "LVP": 15,
    "TILE": 40,
    "CARPET": 10,
}
TEAR_PER_50_SQFT = 1.0
TEAR_CAP = 20.0
BACKORDER_PER_EVENT = 5.0
BACKORDER_CAP = 25.0
REMEASURE_FLAT = 10.0
RISK_FLOOR = 0.0
RISK_CEILING = 100.0
APPROVAL_RISK_MAX = 70                 # score <= 70 approvable; > 70 referred to denial

# Pagination defaults (PRD §2.3).
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MAX_LIMIT = 100
