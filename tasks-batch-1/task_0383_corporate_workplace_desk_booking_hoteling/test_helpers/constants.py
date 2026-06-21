"""Domain thresholds — numeric constants from PRD calculations.

Generic NON_EXISTENT_UUID is imported from the framework, not redefined here.
"""

# --- Amenity chargeback (PRD §3.5 / §2.9) ---
SERVICE_FEE_RATE = 0.085
TIER_LOW_MAX_CENTS = 499      # pre-discount total <= 499 -> 0% discount
TIER_MID_MAX_CENTS = 999      # 500..999 -> 5% discount
TIER_LOW_PCT = 0
TIER_MID_PCT = 5
TIER_HIGH_PCT = 10            # >= 1000 -> 10% discount

# --- Strike score (PRD §3.6) ---
STRIKE_WEIGHT = 10            # NO_SHOW delta = +10
GOOD_CREDIT = 3              # GOOD_CHECKIN delta = -3
SUSPEND_THRESHOLD = 30       # booking_privilege SUSPENDED when strike_score >= 30

# --- Utilization (PRD §3.11) ---
DECIMAL_PLACES = 2

# --- Floor workday defaults (PRD §2.7) ---
DEFAULT_WORKDAY_START_MINUTE = 540
DEFAULT_WORKDAY_END_MINUTE = 1080
DEFAULT_CAPACITY_MINUTES = DEFAULT_WORKDAY_END_MINUTE - DEFAULT_WORKDAY_START_MINUTE  # 540

# --- Capacity policy defaults (PRD §3.3) ---
DEFAULT_MAX_ACTIVE_RESERVATIONS = 1
DEFAULT_GRACE_MINUTES = 30
DEFAULT_ENFORCE_TEAM_ZONING = True

# --- Neighborhood defaults (PRD §3.1) ---
DEFAULT_CAPACITY_CAP_PCT = 100

# --- Room defaults (PRD §3.1) ---
DEFAULT_TURNOVER_BUFFER_MINUTE = 15
