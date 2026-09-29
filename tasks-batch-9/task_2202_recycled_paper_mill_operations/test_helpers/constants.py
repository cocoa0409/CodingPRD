"""Domain thresholds and numeric constants stated in the PRD."""

# --- fiber pricing -----------------------------------------------------------
FUEL_SURCHARGE_RATE = 0.185
VOLUME_TIER_1_FLOOR = 100_000.00
VOLUME_TIER_2_FLOOR = 250_000.00
VOLUME_DISCOUNT_NONE = 0.000
VOLUME_DISCOUNT_TIER_1 = 0.015
VOLUME_DISCOUNT_TIER_2 = 0.030
MAX_REPRICE_REVISIONS = 2
PROBATION_TONNAGE_CAP = 500.00
PO_CLOSE_FRACTION = 0.98

# --- weighbridge -------------------------------------------------------------
MOISTURE_REJECT_MARGIN_PCT = 5.00

# --- supplier posture ladder -------------------------------------------------
STRIKES_FOR_SUSPENDED = 4
STRIKES_FOR_PROBATION = 2

# --- pulping -----------------------------------------------------------------
YIELD_FLOOR_PCT = 45.00
CONTAMINATION_YIELD_PENALTY_PER_PCT = 1.8
BLEND_CONTAMINATION_CEILING_PCT = 3.500
REJECT_TONS_FRACTION_CEILING = 0.40

# --- deink chemistry ---------------------------------------------------------
CAUSTIC_USD_PER_KG = 0.62
PEROXIDE_USD_PER_KG = 1.15
SURFACTANT_USD_PER_KG = 3.40
TISSUE_PREMIUM_MULTIPLIER = 1.10
EFFECTIVENESS_DECAY_BASE = 0.65
BASE_REMOVAL_FRACTION = 0.35
SURFACTANT_DOSE_COEFFICIENT = 0.08
MAX_REMOVAL_FRACTION = 0.95
INK_LOAD_PCT = 4.50
MAX_DEINK_PASSES = 3

# --- grade change ------------------------------------------------------------
BASIS_WEIGHT_DELTA_TIER_1 = 10.0
BASIS_WEIGHT_DELTA_TIER_2 = 40.0
WASTE_TIER_1_TONS = 0.800
WASTE_TIER_2_TONS = 2.500
WASTE_TIER_3_TONS = 5.000
BRIGHTNESS_PENALTY_TONS = 1.500
FAMILY_CROSS_MULTIPLIER = 2.20
DIRECTION_DOWN_MULTIPLIER = 1.15
TRANSITION_WASTE_CEILING_TONS = 12.000

# --- run quality -------------------------------------------------------------
PERFECT_SCORE = 100.00
BASIS_WEIGHT_PENALTY_PER_PCT = 4.0
MOISTURE_PENALTY_PER_PCT = 12.0
STRENGTH_PENALTY_COEFFICIENT = 30.0
OFF_SPEC_BASIS_WEIGHT_DEVIATION_PCT = 5.00
CERTIFICATION_INDEX_FLOOR = 85.00

# --- customer orders / roll sets ---------------------------------------------
MAX_DESCHEDULES = 3
MAX_REWINDS = 2

# --- effluent ----------------------------------------------------------------
EXCEEDANCE_RATIO = 1.00
WATCH_RATIO = 0.90
EXCEEDANCE_DAY_COUNT_TRIGGER = 2
DEFAULT_ROLLING_WINDOW_DAYS = 30

# --- steam header ------------------------------------------------------------
HEADER_CAPACITY_TPH = 180.000
MIN_VIABLE_TPH = 5.000
COGEN_BAND_1_TPH = 30.000
COGEN_BAND_2_TPH = 30.000
COGEN_BAND_1_RATE = 4.10
COGEN_BAND_2_RATE = 6.75
COGEN_BAND_3_RATE = 9.20

# --- logical clock -----------------------------------------------------------
DEFAULT_CLOCK_INSTANT = "2026-08-01T00:00:00Z"

# --- pagination --------------------------------------------------------------
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MAX_LIMIT = 100
