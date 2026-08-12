"""Domain thresholds — numeric constants stated in PRD §3 calculations prose."""

# PRD §3.8 forward projection
PRE_SALE_SELLOUT_FACTOR = 0.65
POST_SALE_DECAY = 0.35
PER_TICKET_VARIABLE_COST_CENTS = 350

# PRD §3.7 settlement variance grading
VARIANCE_THRESHOLD_CENTS = 50000
MATERIAL_VARIANCE_CENTS = 500000

# PRD §3.2 routing leg drive time
AVG_SPEED_MPH = 55
MAX_DRIVE_MINUTES_BEFORE_REST = 480

# PRD §3.3 / §3.4 on-sale lead
MIN_ON_SALE_LEAD_DAYS = 14

# PRD §3.3 hold lifecycle
HOLD_TTL_HOURS = 72
COUNTER_EXTENSION_HOURS = 24
MAX_COUNTER_ROUNDS = 3

# PRD §2.5 logical clock startup default
DEFAULT_LOGICAL_CLOCK = "2026-05-01T00:00:00Z"
