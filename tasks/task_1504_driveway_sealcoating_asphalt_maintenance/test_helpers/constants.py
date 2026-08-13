"""Domain thresholds and rates from the PRD's pricing, scheduling, and cure rules."""

# --- Pavement condition index (PRD §3.2) ---
CRACK_WEIGHT = 400
POTHOLE_WEIGHT = 700
OIL_WEIGHT = 300
CRACK_CAP = 40
POTHOLE_CAP = 35
OIL_CAP = 15
SLOPE_DEDUCTION_STEEP = 10
SLOPE_DEDUCTION_MODERATE = 5
SLOPE_DEDUCTION_NONE = 0

# --- Job pricing (PRD §3.3) ---
TIER1_MAX_SQFT = 1000
TIER1_RATE_CENTS = 30
TIER2_MAX_SQFT = 5000
TIER2_RATE_CENTS = 24
TIER3_RATE_CENTS = 18
GRADE_FACTOR = {"STANDARD": 1.00, "PREMIUM": 1.35, "ECO": 1.15}
CRACK_RATE_CENTS_PER_FT = 150
PATCH_RATE_CENTS_PER_SQFT = 800
STRIPE_RATE_CENTS_PER_FT = 90
MOBILIZATION_FEE_CENTS = 7500
MOBILIZATION_WAIVER_SUBTOTAL_CENTS = 200000
MINIMUM_CHARGE_CENTS = 25000
LABOR_FLOOR_CENTS_PER_SQFT = 5
MAX_DISCOUNT_PCT = 0.30

# --- Invoice settlement (PRD §3.9) ---
SURCHARGE_TIER1_MAX_CENTS = 100000
SURCHARGE_TIER1_PCT = 0.06
SURCHARGE_TIER2_MAX_CENTS = 500000
SURCHARGE_TIER2_PCT = 0.04
SURCHARGE_TIER3_PCT = 0.02

# --- Material reservation (PRD §3.5) ---
WASTE_FACTOR = 1.10

# --- Cure window projection (PRD §3.5) ---
COLD_CURE_THRESHOLD_F = 55
COLD_CURE_MULTIPLIER = 1.5
WET_CURE_EXTENSION_HOURS = 12

# --- ADA stall requirement (PRD §3.8) ---
STALL_LINE_FT = 18
ADA_MARKING_FT = 40

# --- Route density gates (PRD §2.10, §3.5) ---
MAX_ROUTE_DRIVE_MINUTES = 180

# --- Season window (PRD §2.7) ---
SEASON_START_MONTH_DAY = "04-01"
SEASON_END_MONTH_DAY = "10-31"

# --- Quote / assessment / warranty clocks ---
QUOTE_EXPIRY_DAYS = 14
ASSESSMENT_SHELF_LIFE_DAYS = 30
TWO_COAT_WARRANTY_EXTENSION_MONTHS = 6

# --- Displacement notice (PRD §3.6) ---
NOTICE_LEAD_HOURS = 48

# --- Weather-hold cascade thresholds (PRD §2.8) ---
HOLD_PRECIP_PROBABILITY_PCT = 60
HOLD_MIN_TEMP_F = 40

# --- Logical clock startup default (PRD §2.7) ---
CLOCK_START_ISO = "2026-08-01T00:00:00Z"
DEFAULT_SERVICE_DATE = "2026-08-10"
SERVICE_MORNING_ISO = "2026-08-10T07:00:00Z"
CURE_COMPLETE_ISO = "2026-08-12T07:00:00Z"

# --- Standard test fixtures ---
STANDARD_MATERIAL = {
    "product_name": "SealMaster Standard",
    "grade": "STANDARD",
    "coverage_sqft_per_gallon": 80,
    "min_apply_temp_f": 50,
    "max_precip_probability_pct": 40,
    "cure_hours_vehicle": 48,
    "reapplication_months": 24,
    "warranty_months": 12,
    "price_per_gallon_cents": 900,
}
PREMIUM_MATERIAL = {
    "product_name": "SealMaster Premium",
    "grade": "PREMIUM",
    "coverage_sqft_per_gallon": 70,
    "min_apply_temp_f": 50,
    "max_precip_probability_pct": 40,
    "cure_hours_vehicle": 48,
    "reapplication_months": 36,
    "warranty_months": 24,
    "price_per_gallon_cents": 1400,
}
PASSING_WEATHER = {
    "min_temp_f": 65,
    "max_temp_f": 82,
    "precip_probability_pct": 10,
    "precipitation_mm": 0,
    "source": "FORECAST",
}
