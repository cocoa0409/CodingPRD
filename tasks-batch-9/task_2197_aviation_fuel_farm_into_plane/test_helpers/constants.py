"""Domain thresholds and default test values drawn from the PRD's stated numbers."""

# --- Volume correction ------------------------------------------------------
REFERENCE_TEMPERATURE_C = 15.0
COEFF_HIGH_DENSITY = 0.000850      # certificate/tank density >= 800.0
COEFF_MID_DENSITY = 0.000900       # density >= 780.0
COEFF_LOW_DENSITY = 0.000950       # everything below 780.0
DENSITY_BAND_HIGH = 800.0
DENSITY_BAND_MID = 780.0
WATER_DEDUCTION_CAP_RATE = 0.005   # one half of one percent of the governing gross

# --- Tank / farm gating ----------------------------------------------------
WATER_BOTTOM_QUARANTINE_MM = 25.0
PERMIT_UTILISATION_RESTRICT_RATIO = 0.90
DEFAULT_UNPUMPABLE_BOTTOM_LITERS = 500.0
DEFAULT_MAX_REPORTABLE_SPILL_LITERS = 20.0

# --- Filter element life ---------------------------------------------------
ELEMENT_NOMINAL_LITERS = 4_000_000.0
ELEMENT_NOMINAL_DAYS = 365
MAX_DIFFERENTIAL_PRESSURE_KPA = 103.0
ELEMENT_LIFE_DUE_PCT = 100.0

# --- Reliability -----------------------------------------------------------
RELIABILITY_START = 100
RELIABILITY_STEP_LITERS = 10
RELIABILITY_POINTS_PER_STEP = 5
RELIABILITY_SEVERITY_CAP = 40
RELIABILITY_SURFACE_MULTIPLIER = {
    "APRON": 1,
    "TANK_BUND": 1,
    "UNSEALED_GROUND": 2,
    "STORM_DRAIN": 2,
}
RELIABILITY_DOWN_THRESHOLD = 60

# --- Pricing ---------------------------------------------------------------
TIER_VOLUME_HIGH_LITERS = 500_000.0
TIER_VOLUME_MID_LITERS = 100_000.0
TIER_DIFF_HIGH_CENTS = 1.60
TIER_DIFF_MID_CENTS = 2.40
TIER_DIFF_BASE_CENTS = 3.20
INTO_PLANE_FEE_MINIMUM_CENTS = 2500
INTO_PLANE_FEE_RATE_CENTS_PER_LITER = 0.45
FLOWAGE_FEE_RATE_CENTS_PER_LITER = 0.12
FEDERAL_EXCISE_RATE_CENTS_PER_LITER = 1.14
STATE_SALES_TAX_RATE = 0.0725

# --- Invoicing -------------------------------------------------------------
REBATE_HIGH_VOLUME_LITERS = 250_000.0
REBATE_MID_VOLUME_LITERS = 100_000.0
REBATE_RATE_HIGH = 0.015
REBATE_RATE_MID = 0.0075
ADMIN_FEE_CAP_CENTS = 50_000
ADMIN_FEE_RATE = 0.004

# --- Tolerances and round ceilings ----------------------------------------
UPLIFT_POSTING_TOLERANCE = 1.05     # 105 percent of max_authorized_liters when posting
VARIANCE_HOLD_PCT = 0.50            # strictly greater than 0.50 percent holds the run
MAX_RETEST_ROUND = 2                # re-sample allowed only while retest_round <= 1
MAX_DISPUTE_ROUND = 2               # dispute allowed only while dispute_round <= 1
AUTHORIZATION_VALIDITY_HOURS = 2
DEFAULT_TURNAROUND_BUFFER_MINUTES = 15

# --- Clock -----------------------------------------------------------------
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"

# --- Pagination -----------------------------------------------------------
PAGINATION = {"default_limit": 10, "min_limit": 1, "max_limit": 100, "min_offset": 0}

# --- Handy test defaults --------------------------------------------------
TEST_DEFAULTS = {
    "TANK_CAPACITY_LITERS": 1_000_000.0,
    "TANK_SAFE_FILL_LITERS": 900_000.0,
    "TANK_DENSITY": 800.0,
    "PERMIT_MAX_DAILY_THROUGHPUT": 5_000_000.0,
    "CREDIT_LIMIT_CENTS": 100_000_000_000,
    "BASE_PRICE_CENTS_PER_LITER": 80.0,
}
