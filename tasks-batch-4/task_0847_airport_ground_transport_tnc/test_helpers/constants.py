"""Domain thresholds — numeric constants from the PRD's calculation and
validation rules (PRD §2.8, §3.3, §3.5, §3.7, §3.8)."""

# --- Trip fee (PRD §3.5) ---
BASE_FEE_CENTS_BY_TYPE = {"TNC": 350, "TAXI": 300, "LIMO": 500, "SHUTTLE": 200}
PEAK_HOURS_UTC = [7, 8, 9, 16, 17, 18]
PEAK_MULTIPLIER = 1.5
WAV_DISCOUNT_CENTS = 100
FEE_FLOOR_CENTS = 200
DEADHEAD_FEE_CENTS = 100

# --- Penalty scoring (PRD §3.1, §3.7) ---
PENALTY_POINTS_BY_TYPE = {
    "STAGING": 3,
    "CURB": 4,
    "AVI_MISMATCH": 6,
    "NO_DECAL": 6,
    "WAV_SHORTFALL": 5,
}
ROLLING_WINDOW_DAYS = 90
SUSPENSION_THRESHOLD_POINTS = 12

# --- Settlement (PRD §2.8, §3.8) ---
ADMIN_RATE = 0.025
WAV_INCENTIVE_CENTS = 50

# --- Staging cooldown / appeal window (PRD §3.3, §3.7) ---
STAGING_COOLDOWN_MINUTES = 30
APPEAL_WINDOW_DAYS = 14

# --- Pagination (PRD §2.3) ---
PAGINATION_LIMIT_MIN = 1
PAGINATION_LIMIT_MAX = 100

# --- Geofence test coordinates (a lot center inside which the default join sits) ---
LOT_CENTER_LAT = 40.64
LOT_CENTER_LNG = -73.78
LOT_RADIUS_M = 5000
