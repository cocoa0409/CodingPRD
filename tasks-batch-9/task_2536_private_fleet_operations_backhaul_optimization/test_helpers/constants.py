"""Domain thresholds and defaults drawn from the PRD's calculation rules."""

# Service-minute allowances per stop type (PRD trip planning arithmetic).
FIXED_DELIVERY_SETUP_MINUTES = 15
FIXED_PICKUP_MINUTES = 45
FIXED_DROP_OFF_MINUTES = 20
FIXED_FUEL_MINUTES = 25
MANDATORY_BREAK_MINUTES = 30
BREAK_TRIGGER_DRIVE_MINUTES = 480

# Hours-of-service ceilings.
MAX_DAILY_DRIVE_MINUTES = 660
MAX_DAILY_DUTY_MINUTES = 840
MAX_WEEKLY_ON_DUTY_MINUTES = 4200

# Driver pay.
DETENTION_GRACE_MINUTES = 30

# Backhaul contribution margin.
VARIABLE_COST_CENTS_PER_MILE = 185
HANDLING_CENTS_PER_CASE = 9
REEFER_SURCHARGE_CENTS_PER_MILE = 22
COMMISSION_TIER_MARGIN_PCT = 0.20
COMMISSION_PCT_HIGH = 0.06
COMMISSION_PCT_LOW = 0.03
MIN_MARGIN_PCT = 0.08
MAX_REVIEW_ROUNDS = 3

# Domicile cost benchmark.
FUEL_CENTS_PER_MILE = 62
MAINTENANCE_CENTS_PER_MILE = 19

# Domicile balance index gates for a borrowed driver.
REBALANCE_SOURCE_MIN_INDEX = 1.5
REBALANCE_TARGET_MAX_INDEX = 1.0

# Driver safety scoring.
BASE_POINTS = {
    "HARD_BRAKE": 2,
    "SPEEDING": 3,
    "FOLLOWING_DISTANCE": 2,
    "SEATBELT": 4,
}
SAFETY_SCORE_FLOOR = 0
SAFETY_SCORE_CEILING = 100
COACHING_HOLD_THRESHOLD = 70
MIN_BID_SAFETY_SCORE = 80

# Preventive maintenance.
PM_WINDOW_MINUTES = 480
MAX_DEFERRALS = 2

# Maintenance / trip collision buffer.
SHOP_BUFFER_MINUTES = 120

# Rest between committed trips.
MIN_REST_MINUTES = 600

# Envelope and pagination.
DEFAULT_PAGE_LIMIT = 10
MAX_PAGE_LIMIT = 100

# The logical clock's default instant.
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

# A syntactically valid UUID that names no row of any entity.
UNKNOWN_UUID = "b1e7c3aa-5f2d-4e11-9c88-0000deadbeef"
