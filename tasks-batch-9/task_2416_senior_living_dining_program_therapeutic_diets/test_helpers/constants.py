"""Domain thresholds and rate tables stated in the PRD."""

# --- Logical clock (PRD §2.5) --------------------------------------------
#: Before any call to the clock-setting endpoint the logical clock reads this.
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

# --- Community policy dials (PRD §3.1) -----------------------------------
DEFAULT_GUEST_MEAL_SPONSOR_CAP_CENTS = 20000
DEFAULT_VARIANCE_TOLERANCE_CENTS = 5000

# --- Venue scheduling dials (PRD §3.1) -----------------------------------
DEFAULT_SEATING_TURN_MINUTES = 60
MIN_SEATING_TURN_MINUTES = 15
DEFAULT_TURNOVER_BUFFER_MINUTES = 20

# --- Texture / liquid ranks (PRD §3.2) -----------------------------------
TEXTURE_RANKS = {
    "REGULAR": 0,
    "BITE_SIZED": 1,
    "MINCED_MOIST": 2,
    "PUREED": 3,
}
LIQUID_RANKS = {
    "THIN": 0,
    "SLIGHTLY_THICK": 1,
    "MILDLY_THICK": 2,
    "MODERATELY_THICK": 3,
    "EXTREMELY_THICK": 4,
}

# --- Review loop ceiling (PRD §3.2 / §3.4) -------------------------------
#: A REQUEST_CHANGES decision is only accepted while review_round < 3.
REVIEW_ROUND_CEILING = 3

# --- Tray-card trigger priority (PRD §3.3) -------------------------------
TRIGGER_PRIORITY = {"ALLERGEN": 0, "TEXTURE": 1, "DISLIKE": 2}

# --- Committee refresh (PRD §3.4) ----------------------------------------
QUORUM_PARTICIPATION_PCT = 40.00
TIER_WEIGHTS = {"QUORUM": 1.0, "ADVISORY": 0.6}
REFRESH_THRESHOLDS = {"QUORUM": 25.00, "ADVISORY": 40.00}
VOTE_WEIGHT_BY_CARE_LEVEL = {
    "INDEPENDENT_LIVING": 1,
    "ASSISTED_LIVING": 1,
    "MEMORY_CARE": 2,
    "SKILLED_NURSING": 2,
}

# --- Reservation geometry (PRD §3.5) -------------------------------------
#: Resident-side occupation widens 90 minutes on each side, closed interval.
MEAL_SPACING_WINDOW_MINUTES = 90

# --- Ticket rate table (PRD §3.6) ----------------------------------------
TICKET_BASE_RATES = {
    "RESIDENT": {"BREAKFAST": 400, "LUNCH": 650, "DINNER": 800},
    "GUEST": {"BREAKFAST": 850, "LUNCH": 1250, "DINNER": 1650},
    "TAKEOUT": {"BREAKFAST": 700, "LUNCH": 1100, "DINNER": 1450},
}
GUEST_DISCOUNT_PCT = 12.5
TAKEOUT_PACKAGING_FEE_CENTS = 175
MEALS_TAX_PCT = 7.25

# --- Temperature limits (PRD §3.7) ---------------------------------------
TEMPERATURE_LIMITS = {
    "HOT_HOLDING": 135.0,
    "COLD_HOLDING": 41.0,
    "REHEAT": 165.0,
}
POSTURE_SUSPENDED_AT_COUNT = 3
POSTURE_WATCH_AT_COUNT = 2

# --- Monitoring thresholds (PRD §3.8) ------------------------------------
WEIGHT_BREACH_PCT = -5.00
INTAKE_BREACH_PCT = 50.00
ROLLING_WINDOW_DAYS = 30
INTAKE_AVERAGE_WINDOW_DAYS = 7
ON_LEAVE_RISK_MULTIPLIER = 0.50

# --- Reconciliation fee waterfall (PRD §3.9) -----------------------------
FEE_TIER_SMALL_MAX_CENTS = 3500
FEE_TIER_MID_MAX_CENTS = 20000
FEE_RATES = {"SMALL": 6.0, "MID": 4.5, "LARGE": 3.0}
#: Census projection prices every counted reservation at the RESIDENT rate.
RESIDENT_TRANSFER_RATES = {"BREAKFAST": 400, "LUNCH": 650, "DINNER": 800}

# --- Pagination (PRD §2.3) -----------------------------------------------
DEFAULT_LIMIT = 10
MAX_LIMIT = 100
