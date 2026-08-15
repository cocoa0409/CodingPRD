"""Domain thresholds and shared constants drawn from PRD sections 2 and 3."""

# --- Logical clock (PRD 2.5) ---
# At server startup the logical clock reads exactly this instant.
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"
DEFAULT_CLOCK_DATE = "2026-08-01"

# --- Weight reconciliation (PRD 3.4) ---
TARE_G = {
    "NEWBORN": 28,
    "SMALL": 34,
    "MEDIUM": 40,
    "LARGE": 46,
    "XL": 52,
}
SOIL_FACTOR_MILLI = 2500
VARIANCE_THRESHOLD_PCT = 10.00

# --- Route operations (PRD 3.3) ---
ROUTE_CAPACITY_ITEMS = 4000
STOP_BUFFER_MIN = 15

# --- Pauses (PRD 3.7) ---
MIN_NOTICE_DAYS = 3
MAX_PAUSE_DAYS = 28

# --- Invoices (PRD 3.9) ---
PAST_DUE_DAYS = 14

# --- Wash chemistry (PRD 3.5) ---
MIN_DOSE_ML = 60
MAX_DOSE_ML = 900
SOIL_MULTIPLIER = {"LIGHT": 0.9, "NORMAL": 1.0, "HEAVY": 1.25}
HARDNESS_MULTIPLIER = {"SOFT": 0.95, "MEDIUM": 1.0, "HARD": 1.15}

# --- Lost item schedule (PRD 3.8) ---
REPLACEMENT_COST_CENTS = {
    "NEWBORN": 250,
    "SMALL": 275,
    "MEDIUM": 300,
    "LARGE": 325,
    "XL": 350,
}
SURCHARGE_THRESHOLD = 0.50
SURCHARGE_MULTIPLIER = 1.10

# --- Size ladder (PRD 3.6) ---
SIZE_LADDER = ["NEWBORN", "SMALL", "MEDIUM", "LARGE", "XL"]

# --- Catalog defaults used across the suite (PRD 3.1) ---
STANDARD_PLAN = {
    "tier_code": "STANDARD",
    "weekly_quota": 80,
    "weekly_fee_cents": 3900,
    "overage_rate_cents": 10,
    "overage_cap_items": 20,
    "deposit_cents": 18000,
    "service_bags_per_week": 1,
    "weight_policy": "COUNT_BASIS",
    "kit_reserve_pct": 10,
}

ESSENTIAL_PLAN = {
    "tier_code": "ESSENTIAL",
    "weekly_quota": 60,
    "weekly_fee_cents": 3200,
    "overage_rate_cents": 12,
    "overage_cap_items": 20,
    "deposit_cents": 15000,
    "service_bags_per_week": 1,
    "weight_policy": "COUNT_BASIS",
    "kit_reserve_pct": 10,
}

ZONE_NORTH_WEEKDAYS = ["MON", "THU"]
ZONE_TRI_WEEKDAYS = ["MON", "WED", "FRI"]

DEFAULT_WINDOW_START_MINUTES = 480
DEFAULT_WINDOW_END_MINUTES = 720

# F-SANI formula used by the wash-plant flows (PRD 3.5 worked constants).
FORMULA_F_SANI = {
    "formula_code": "F-SANI",
    "base_detergent_ml_per_kg": 45,
    "sanitizer_ml_per_kg": 8,
    "min_temp_celsius": 71,
    "min_dwell_seconds": 180,
    "chlorine_ppm_min": 50,
    "chlorine_ppm_max": 200,
    "max_rewash_count": 2,
}

# Standard route date: a Monday inside the Z-NORTH weekday set.
ROUTE_DATE_MON = "2026-08-03"
ROUTE_DATE_THU = "2026-08-06"
ROUTE_DATE_MON_WEEK2 = "2026-08-10"
