"""Domain thresholds and rates stated in the PRD's calculation narratives."""

# --- Shrink valuation (PRD §3.9) -----------------------------------------
HANDLING_CENTS_PER_KG = 85
DISPOSAL_BASE_CENTS_PER_KG = 40
DISPOSAL_FACTOR_UNSOLD_FRESH = 1.0
DISPOSAL_FACTOR_MISLABEL_DESTRUCTION = 1.5
DISPOSAL_FACTOR_COLD_CHAIN_DISPOSAL = 2.0

# --- Cook-and-sell recovery (PRD §3.9) -----------------------------------
MAX_CONVERSION_SHARE = 0.60
COOK_YIELD_RATIO = 0.65
PREVIOUSLY_FROZEN_PENALTY = 0.15
FRESH_CLAIM_PENALTY = 0.05
COOK_LABOR_CENTS_PER_KG = 90

# --- Supplier chargeback assessment (PRD §3.8) ---------------------------
BASE_PENALTY_CENTS = 25_000
RELABEL_LABOR_CENTS = 4_000
GOODWILL_TIER_1_RATE = 0.15
GOODWILL_TIER_2_RATE = 0.08
GOODWILL_TIER_3_RATE = 0.00
GOODWILL_TIER_2_FLOOR_CENTS = 50_000
GOODWILL_TIER_3_FLOOR_CENTS = 120_000
PROBATION_MULTIPLIER = 1.25

# --- Substitution risk indices (PRD §3.8) --------------------------------
MISMATCH_BASE_WEIGHT = 40
HIGH_RISK_BONUS = 10
INDEX_CAP = 100.00
SUPPLIER_PROBATION_THRESHOLD = 25.00
SUPPLIER_SUSPENSION_THRESHOLD = 60.00
MIN_SAMPLES_FOR_STANDING = 2

# --- Verification sampling plan (PRD §3.8) -------------------------------
BASE_SAMPLES = 1
HIGH_RISK_DIVISOR = 3
HIGH_RISK_SURCHARGE_SAMPLES = 2
RISK_SURCHARGE_THRESHOLD = 40.00

# --- Cold chain (PRD §3.7) -----------------------------------------------
ICE_BED_LIMIT_C = 4.4
MINOR_MAX_MINUTES = 60
MAJOR_MAX_MINUTES = 180

# --- Counter posture (PRD §2.6) ------------------------------------------
POINTS_SPECIES_SUBSTITUTION = 6
POINTS_COOL_MISSING = 4
POINTS_FROZEN_DISCLOSURE = 4
POINTS_SIMP_DEFICIENT = 5
POINTS_COLD_CHAIN = 3
POINTS_UNSUBSTANTIATED_CLAIM = 6
SUSPEND_EXCURSION_COUNT = 2
SUSPEND_VIOLATION_POINTS = 12
RESTRICT_EXCURSION_COUNT = 1
RESTRICT_VIOLATION_POINTS = 6

# --- Ice-bed slot occupancy (PRD §3.3) -----------------------------------
SANITATION_BUFFER_MINUTES = 30

# --- Supplier credit hold (PRD §3.1) -------------------------------------
CREDIT_HOLD_CENTS = 75_000

# --- Verification sample retest bound (PRD §3.8) -------------------------
MAX_RETESTS = 2

# --- Pagination (PRD §2.3) -----------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100

# --- Logical clock (PRD §2.4) --------------------------------------------
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"
