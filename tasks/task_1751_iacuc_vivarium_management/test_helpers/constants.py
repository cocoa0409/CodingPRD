"""Domain thresholds and rates (PRD §3.4, §3.5, §3.7, §3.8, §3.9)."""

# Per-diem daily rates in integer cents (PRD §3.7).
RATE_CENTS = {
    "MOUSE": 125,
    "RABBIT": 400,
    "ZEBRAFISH": 40,
    "RAT_PUP": 75,
    "RAT_ADULT": 150,
    "RAT_AGED": 210,
}

# Institutional policy caps on adult occupancy per cage (PRD §3.4).
CAPACITY_POLICY = {
    "MOUSE": 5,
    "RAT": 2,
    "RABBIT": 1,
    "ZEBRAFISH": 20,
}

# Temporal thresholds.
PUP_AGE_DAYS = 21              # nursing-exemption age boundary (PRD §3.4/§3.5)
RAT_AGED_AGE_DAYS = 365        # rat aged-tier boundary (PRD §3.7)
SEMIANNUAL_DAYS = 180          # inspection due-by interval (PRD §3.9)
TURNOVER_MINUTES = 30          # room-booking turnover buffer (PRD §3.9)
RESOLUTION_DEADLINE_HOURS = 72 # adverse-event resolve window (PRD §3.8)
ENROLLMENT_VALIDITY_DAYS = 365 # training / occ-health expiry (PRD §3.2)
PROTOCOL_TERM_YEARS = 3        # approved protocol expiry (PRD §3.3)

# Logical clock default at server startup (PRD §2.4).
CLOCK_DEFAULT_ISO = "2026-08-01T00:00:00Z"

# Shared scenario dates.
GRANT_EXPIRES_ISO = "2027-01-01T00:00:00Z"
ADULT_MOUSE_DOB = "2026-05-01T00:00:00Z"
ADULT_RAT_DOB = "2026-01-01T00:00:00Z"
AGED_RAT_DOB = "2024-01-01T00:00:00Z"
BREEDING_ADULT_DOB = "2025-12-01T00:00:00Z"
DEFAULT_PERIOD_START = "2026-08-01T00:00:00Z"
DEFAULT_PERIOD_END = "2026-08-22T00:00:00Z"   # 21 billable days

TEST_DEFAULTS = {
    "GRANT_BUDGET_CENTS": 500000,
    "MAX_ANIMALS_JUSTIFIED": 10,
}
