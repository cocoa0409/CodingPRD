"""Domain thresholds and numeric constants from the PRD calculations."""

# Logical clock default (PRD §2.8): server startup instant.
DEFAULT_CLOCK = "2026-07-01T00:00:00Z"

# Exchange points-cost pricing (PRD §3.3).
MIN_EXCHANGE_POINTS = 100
SEASON_PEAK_MULT = 1.5      # months 6, 7, 8, 12
SEASON_SHOULDER_MULT = 1.2  # months 3, 4, 5, 9, 10, 11
SEASON_OFF_MULT = 1.0       # months 1, 2
PEAK_MONTHS = [6, 7, 8, 12]
SHOULDER_MONTHS = [3, 4, 5, 9, 10, 11]
OFF_MONTHS = [1, 2]

# Membership discounts on points cost (PRD §3.3).
MEMBERSHIP_DISCOUNT = {
    "BASIC": 0.0,
    "PLUS": 0.10,
    "PREMIER": 0.20,
    None: 0.0,
}

# Welcome bonus granted at membership activation (PRD §3.1).
WELCOME_BONUS = {
    "BASIC": 500,
    "PLUS": 1000,
    "PREMIER": 2000,
}

# Damage coverage limit set at confirm from host tier (PRD §3.6/§3.7).
COVERAGE_LIMIT = {
    "BASIC": 2000,
    "PLUS": 5000,
    "PREMIER": 10000,
    None: 0,
}

# Damage payout formula (PRD §3.7).
FIXED_DEDUCTIBLE_POINTS = 50
DEDUCTIBLE_RATE_LOW = 0.20   # amount <= 500
DEDUCTIBLE_RATE_MID = 0.10   # 500 < amount <= 2000
DEDUCTIBLE_RATE_HIGH = 0.05  # amount > 2000
LOW_BAND_MAX = 500
MID_BAND_MAX = 2000

# Cancellation refund windows (PRD §3.6).
FULL_REFUND_MIN_DAYS = 7
PARTIAL_REFUND_MIN_DAYS = 2
PARTIAL_REFUND_PCT = 0.5

# Trust score weights (PRD §3.6).
TRUST_BASE = 50
COMPLETED_WEIGHT = 2
DAMAGE_PENALTY = 10
DISPUTE_PENALTY = 15
TRUST_FLOOR = 0
TRUST_CEILING = 100

# Deadlines / buffers (PRD §3.3, §3.5).
REQUEST_TTL_DAYS = 7
TRAVEL_BUFFER_DAYS = 1

# Pagination defaults (PRD §2.3).
DEFAULT_LIMIT = 10
MAX_LIMIT = 100
