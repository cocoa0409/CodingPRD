"""Domain thresholds and numeric constants from the PRD (§2.6, §3.5, §3.7, §3.8)."""

# --- Edition defaults used across setups -------------------------------------
DEFAULT_MAX_JUDGES_PER_PROJECT = 2
DEFAULT_MIN_QUORUM_RATIO_PCT = 50
DEFAULT_ADVANCEMENT_SLOTS = 1

# --- Logical clock (PRD §2.5) -------------------------------------------------
# Startup value of the server-side logical clock.
CLOCK_STARTUP_UTC = "2026-08-01T00:00:00Z"

# --- Inspection windows (PRD §3.6) --------------------------------------------
# Default window deliberately brackets the startup clock reading so a PASS
# recorded without touching the clock falls inside the window.
DEFAULT_WINDOW_START = "2026-08-01T00:00:00Z"
DEFAULT_WINDOW_END = "2026-08-10T00:00:00Z"

# --- Scholarship waterfall caps, integer cents (PRD §3.8) ----------------------
GRAND_PRIZE_CAP_CENTS = 400000
CATEGORY_FIRST_CAP_CENTS = 300000
CATEGORY_SECOND_CAP_CENTS = 150000
SPECIAL_TOPIC_CAP_CENTS = 100000

# --- Mentor recognition points (PRD §3.8) --------------------------------------
POINTS_ADVANCED = 5
POINTS_WAITLISTED_LEADERBOARD = 4  # inclusive variant only (double weight)
POINTS_GRAND_PRIZE = 8
POINTS_CATEGORY_FIRST = 4
POINTS_CATEGORY_SECOND = 2
POINTS_SPECIAL_TOPIC = 1

TIER_BRONZE_MIN = 10
TIER_SILVER_MIN = 25
TIER_GOLD_MIN = 50

# --- Score / aggregate precision (PRD §2.6) ------------------------------------
NORMALIZED_DECIMALS = 3
AGGREGATE_DECIMALS = 2
MIN_MAX_TIE_VALUE = 0.500
Z_SCORE_SD_ZERO_VALUE = 0.000
