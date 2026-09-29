"""Domain thresholds and named constants the PRD's calculations depend on."""

# --- The logical clock ----------------------------------------------------
# The server's clock starts at this instant before any clock write.
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"
# Late in the day, so that earlier same-day instants are never in the future.
TEST_CLOCK_UTC = "2026-08-01T23:00:00Z"

# --- Dwell classification -------------------------------------------------
DWELL_BREWER_LIMIT_DAYS = 30
DWELL_BREWER_APPROACHING_DAYS = 24
DWELL_DISTRIBUTOR_LIMIT_DAYS = 45
DWELL_DISTRIBUTOR_APPROACHING_DAYS = 36
SECONDS_PER_DAY = 86400

# --- Per-fill charging ----------------------------------------------------
DWELL_SURCHARGE_CENTS_PER_DAY = 30
DWELL_SURCHARGE_CAP_PCT = 0.20
VOLUME_TIER_1_CENTS = 4500
VOLUME_TIER_2_CENTS = 9000
VOLUME_TIER_1_DISCOUNT_BP = 150
VOLUME_TIER_2_DISCOUNT_BP = 300

# --- Stainless scrap and loss valuation -----------------------------------
SCRAP_RECOVERY_PCT = 0.65
DEPRECIATION_PER_FILL_BP = 45
DEPRECIATION_CAP_BP = 7000
BOOK_VALUE_FLOOR_PCT = 0.30
LIABILITY_BP = {
    "LOST_IN_TRADE": 6000,
    "DAMAGED_BEYOND_REPAIR": 10000,
    "NOT_RETURNED_DWELL": 10000,
    "STOLEN_SUSPECTED": 0,
}

# --- Brewer standing gates ------------------------------------------------
TRAILING_WINDOW_DAYS = 90
PROBATION_LOSS_RATE_BP = 1500
PROBATION_BALANCE_THRESHOLD_CENTS = 25000
STATUS_REASON_LOSS_RATE = "LOSS_RATE_THRESHOLD"
STATUS_REASON_CHARGEBACK_BALANCE = "CHARGEBACK_BALANCE_THRESHOLD"

# --- Return incentives ----------------------------------------------------
COOPERATION_MULTIPLIER_BP = {
    "NONE": 0,
    "BRONZE": 10000,
    "SILVER": 11500,
    "GOLD": 13000,
}
DWELL_BAND_BP = {
    "at_most_14": 10000,
    "15_to_29": 6000,
    "30_to_44": 2500,
    "at_least_45": 0,
}
SILVER_MIN_RETURNS = 3
SILVER_MIN_ON_TIME_PCT = 90.0
GOLD_MIN_RETURNS = 5
GOLD_MIN_ON_TIME_PCT = 96.0

# --- Certification and servicing ------------------------------------------
PRESSURE_TEST_INTERVAL_FILLS = 25
PRESSURE_TEST_INTERVAL_DAYS = 730
MIN_CAUSTIC_CYCLE_MINUTES = 12
MIN_PRESSURE_TEST_PSI = 30
DEFAULT_INTAKE_BUFFER_HOURS = 4
QUARANTINE_REASON_INSPECTION = "INSPECTION_MAJOR_DEFECT"
QUARANTINE_REASON_PRESSURE_TEST = "PRESSURE_TEST_FAIL"

# --- Reconciliation claims ------------------------------------------------
MAX_CLAIM_ROUNDS = 3
CLAIM_WINDOW_DAYS = 30

# --- Pool posture defaults ------------------------------------------------
DEFAULT_RESTRICT_THRESHOLD_PCT = 25
DEFAULT_FREEZE_THRESHOLD_PCT = 10
DEFAULT_RESTRICTED_MAX_KEGS_PER_ORDER = 2

# --- Agreement defaults ---------------------------------------------------
DEFAULT_REPLENISHMENT_THRESHOLD_PCT = 20
DEFAULT_CREDIT_LIMIT_CENTS = 40000
DEFAULT_RETURN_INCENTIVE_RATE_CENTS_PER_KEG = 250

# --- Pagination -----------------------------------------------------------
DEFAULT_PAGE_LIMIT = 10
MIN_PAGE_LIMIT = 1
MAX_PAGE_LIMIT = 100

# --- Values used repeatedly by the reference test scenarios ---------------
TEST_DEFAULTS = {
    "BREWER_NAME": "Ridgeline Brewing",
    "BREWER_BRAND_CODE": "RDG",
    "BREWER_CREDIT_LIMIT_CENTS": 400000,
    "SECOND_BREWER_NAME": "Copper Kettle Brewing",
    "SECOND_BREWER_BRAND_CODE": "CKB",
    "DISTRIBUTOR_NAME": "Front Range Distributing",
    "DISTRIBUTOR_REGION_CODE": "CO",
    "POOL_CODE": "HB-50L",
    "POOL_SIZE_LITERS": 50,
    "POOL_STAINLESS_WEIGHT_KG": 12.5,
    "POOL_REPLACEMENT_COST_CENTS": 23500,
    "POOL_REGION_CODE": "CO",
    "PER_FILL_RATE_CENTS": 2200,
    "COMMODITY_INDEX_DATE": "2026-07-01",
    "COMMODITY_INDEX_CENTS_PER_KG": 480,
    "COMMODITY_INDEX_SOURCE": "LME_SS304",
    "EFFECTIVE_DATE": "2026-08-01",
    "SERVICE_CENTER_NAME": "Denver Wash Line",
    "SERVICE_CENTER_REGION_CODE": "CO",
}

# The scrap value of one 12.5 kg keg against a 480 c/kg index:
# round_half_up(12.5 * 480 * 0.65) == 3900.
REFERENCE_SCRAP_VALUE_CENTS = 3900
