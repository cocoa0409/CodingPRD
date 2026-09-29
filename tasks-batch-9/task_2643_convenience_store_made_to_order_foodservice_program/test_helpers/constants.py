"""Numeric thresholds and shared literals drawn from the PRD's calculations."""

# ─── Pricing and fees ─────────────────────────────────────────────────
PREMIUM_SURCHARGE_CENTS = 75
CATERING_SERVICE_FEE_BP = 800
CATERING_MIN_SERVICE_FEE_CENTS = 500
CATERING_MIN_SUBTOTAL_CENTS = 5000

# ─── Loyalty ──────────────────────────────────────────────────────────
TIER_MULTIPLIER_BP = {"BASIC": 10000, "PLUS": 12500, "ELITE": 15000}
PLUS_TIER_THRESHOLD_POINTS = 500
ELITE_TIER_THRESHOLD_POINTS = 2000
FUEL_COMBO_BONUS_POINTS = 50
FUEL_LOOKBACK_DAYS = 30

# ─── Kitchen ticketing ────────────────────────────────────────────────
MODIFIER_PREP_SECONDS = 15
STATION_SEQUENCE = ("SANDWICH", "BEVERAGE", "HOT_FOOD", "BAKERY")

# ─── Production and holding ───────────────────────────────────────────
SANITATION_BUFFER_MINUTES = 15

# ─── Order intake windows ─────────────────────────────────────────────
PREORDER_LEAD_MINUTES = 15
CATERING_LEAD_MINUTES = 720

# ─── Labor planning ───────────────────────────────────────────────────
MTO_TXNS_PER_LABOR_HOUR = 18
GRAB_TXNS_PER_LABOR_HOUR = 45
BAKERY_PREP_MINUTES = 120
PEAK_TXN_THRESHOLD = 400
PEAK_MULTIPLIER_BP = 11500
BASE_MULTIPLIER_BP = 10000
MIN_DAYPART_LABOR_MINUTES = 180

# ─── Food safety ──────────────────────────────────────────────────────
PROBE_MIN_READING_F = -40
PROBE_MAX_READING_F = 250
TEMP_LOG_WINDOW_MINUTES = 240
READY_COMPLIANCE_PCT = 90
NOT_READY_COMPLIANCE_PCT = 75
LOCKOUT_STRIKE_COUNT = 2

# ─── Clock and dayparts ───────────────────────────────────────────────
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"
DAYPART_CYCLE = ("BREAKFAST", "LUNCH", "DINNER", "OVERNIGHT")

# ─── Pagination ───────────────────────────────────────────────────────
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100

# ─── Shared test-scenario literals ────────────────────────────────────
STORE_CODE = "WAWA-0101"
STORE_NAME = "Wawa Route 1"
SERVICE_DATE = "2026-08-01"

CLOCK_OVERNIGHT = "2026-08-01T00:00:00Z"
CLOCK_EARLY_BREAKFAST = "2026-08-01T06:00:00Z"
CLOCK_BREAKFAST = "2026-08-01T08:00:00Z"
CLOCK_LATE_BREAKFAST = "2026-08-01T09:00:00Z"
CLOCK_LUNCH = "2026-08-01T11:00:00Z"
