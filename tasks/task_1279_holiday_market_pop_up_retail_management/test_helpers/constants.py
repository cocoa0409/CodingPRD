"""Domain thresholds — numeric constants from PRD calculations (§3)."""

# Application / jury (PRD §3.2, §3.3)
JURY_QUORUM_DEFAULT = 3          # jury_quorum default
MAX_JURY_SCORES = 5              # an application may hold at most 5 scores
JURY_ACCEPT_THRESHOLD = 60       # jury_average must be at least 60 to accept

# Assignment fee computation (PRD §3.4)
EARLY_BIRD_DAYS = 45             # created >= 45 days before opens_at -> 0.85
LATE_COMMIT_DAYS = 7             # created <= 7 days before opens_at -> 1.20
EARLY_BIRD_MULT = 0.85
LATE_COMMIT_MULT = 1.20
HEATING_FLAT_CENTS = 45000       # $450.00 flat heating surcharge (CHALET only)

# Shared POS (PRD §3.6)
SHARED_POS_FEE_BPS_DEFAULT = 250  # 2.50%
POS_FEE_DIVISOR = 10000

# Weather (PRD §3.7)
WEATHER_ALERT_THRESHOLD_WIND_MPH_DEFAULT = 35
WEATHER_LOOKBACK_HOURS = 6

# Renewal score (PRD §3.10)
SALES_DIVISOR = 200000           # $2,000 in cents-per-point
SALES_COMPONENT_CAP = 50
RELIABILITY_BASE = 30
RELIABILITY_PENALTY_PER_STRIKE = 10
JURY_COMPONENT_CAP = 20

# Ops checkpoint (PRD §3.9)
STALE_PENDING_PAYMENT_OPS_RUNS = 3

# Load slots (PRD §3.7)
CHECK_IN_EARLY_MINUTES = 30
COMPLETE_GRACE_MINUTES = 60

# Market open (PRD §3.8)
OPEN_ADVANCE_DAYS = 7

# Logical clock startup default (PRD §1)
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"

# Common fixture instants
SETUP_CLOCK = "2026-10-01T00:00:00Z"      # inside default application window
OPEN_CLOCK = "2026-12-05T00:00:00Z"       # after opens_at, before closes_at
