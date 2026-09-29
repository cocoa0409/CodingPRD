"""Domain thresholds and canonical literals drawn from the PRD."""

# --------------------------------------------------------------------------- #
# The logical clock
# --------------------------------------------------------------------------- #

# The logical clock supplies "now" to every deadline, window and expiry
# comparison, and it starts at this instant.
CLOCK_EPOCH = "2026-08-01T00:00:00Z"

# Standard hours run from 07:00:00Z inclusive to 17:00:00Z exclusive, so this
# instant is inside standard hours and attracts no overtime surcharge.
BUSINESS_HOURS_CLOCK = "2026-08-03T09:00:00Z"
BUSINESS_HOURS_CLOCK_MS = "2026-08-03T09:00:00.000Z"
STANDARD_HOURS_OPEN_CLOCK = "2026-08-03T07:00:00Z"
AFTER_HOURS_CLOCK = "2026-08-03T19:00:00Z"

DEFAULT_LICENSE_EXPIRES_AT = "2027-06-01T00:00:00Z"
DEFAULT_CERTIFIED_UNTIL = "2027-01-01T00:00:00Z"

# --------------------------------------------------------------------------- #
# Numeric thresholds
# --------------------------------------------------------------------------- #

THRESHOLDS = {
    # Pagination
    "PAGE_LIMIT_DEFAULT": 10,
    "PAGE_LIMIT_MIN": 1,
    "PAGE_LIMIT_MAX": 100,
    # Service areas
    "FEE_MULTIPLIER_BP_DEFAULT": 10000,
    "FEE_MULTIPLIER_BP_MIN": 10000,
    "FEE_MULTIPLIER_BP_MAX": 15000,
    "CONCURRENT_WATCH_CAPACITY_DEFAULT": 2,
    # Fee schedules
    "OVERTIME_MULTIPLIER_BP_DEFAULT": 2500,
    # Applicants
    "CREDIT_LIMIT_CENTS_DEFAULT": 500000,
    # Inspector licensing and performance
    "PERFORMANCE_SCORE_START": 100,
    "APPEAL_REVERSAL_PENALTY": 18,
    "CHECK_DEVIATION_PENALTY": 10,
    "LATE_CERTIFICATE_PENALTY": 3,
    "TRAINING_CREDIT_BLOCK_HOURS": 10,
    "TRAINING_CREDIT_CAP": 12,
    "ACTIVATION_MIN_TRAINING_HOURS": 24,
    "ACTIVATION_MIN_SCORE": 80,
    "AUTO_SUSPENSION_SCORE_FLOOR": 70,
    "LATE_CERTIFICATE_HOURS": 48,
    "CHECK_DEVIATION_BAR_PCT": 0.25,
    # Comparison programme
    "SINGLE_CHECK_OUT_OF_TOLERANCE_PCT": 0.50,
    "ROLLING_BIAS_OUT_OF_TOLERANCE_PCT": 0.30,
    "ROLLING_BIAS_DRIFT_WATCH_PCT": 0.15,
    "ROLLING_WINDOW_SIZE": 3,
    "CONSECUTIVE_OUT_OF_TOLERANCE_WITHDRAWAL": 3,
    # Samples
    "PORTIONS_COUNT_MIN": 1,
    "PORTIONS_COUNT_MAX": 10,
    "FILE_RETENTION_DAYS": 90,
    # Weighing
    "DRAFTS_MIN": 1,
    "DRAFTS_MAX": 20,
    "DOCKAGE_PCT_MAX": 15.0,
    "LBS_PER_BUSHEL_CORN": 56,
    "LBS_PER_BUSHEL_SOYBEANS": 60,
    # Vessel watches
    "TRAVEL_BUFFER_MINUTES": 45,
    # Certificates and fees
    "PROTEIN_BASIS_PCT": 13.0,
    "BILLED_THOUSANDS_DIVISOR": 1000,
    "OVERTIME_WINDOW_OPEN_HOUR": 7,
    "OVERTIME_WINDOW_CLOSE_HOUR": 17,
    "DISCOUNT_TIER_1_FLOOR_CENTS": 50000,
    "DISCOUNT_TIER_1_BP": 500,
    "DISCOUNT_TIER_2_FLOOR_CENTS": 150000,
    "DISCOUNT_TIER_2_BP": 1000,
    "REINSPECTION_DEADLINE_DAYS": 5,
    "APPEAL_DEADLINE_DAYS": 10,
    "BOARD_APPEAL_DEADLINE_DAYS": 20,
    # Appeal panels
    "PANEL_SIZE_REINSPECTION": 1,
    "PANEL_SIZE_APPEAL": 3,
    "PANEL_SIZE_BOARD_APPEAL": 5,
}


# --------------------------------------------------------------------------- #
# Grade factor tables (min test weight, max moisture, max damaged total,
# max heat damaged, max foreign material)
# --------------------------------------------------------------------------- #

CORN_GRADE_TABLE = [
    ("US_NO_1", 56.0, 14.0, 3.0, 0.1, 2.0),
    ("US_NO_2", 54.0, 15.0, 5.0, 0.2, 3.0),
    ("US_NO_3", 52.0, 17.5, 7.0, 0.5, 4.0),
    ("US_NO_4", 49.0, 20.0, 10.0, 1.0, 5.0),
    ("US_NO_5", 46.0, 23.0, 15.0, 3.0, 7.0),
]

SOYBEANS_GRADE_TABLE = [
    ("US_NO_1", 56.0, 13.0, 2.0, 0.2, 1.0),
    ("US_NO_2", 54.0, 14.0, 3.0, 0.5, 2.0),
    ("US_NO_3", 52.0, 16.0, 5.0, 1.0, 3.0),
    ("US_NO_4", 49.0, 18.0, 8.0, 3.0, 5.0),
]

LIMITING_FACTOR_ORDER = [
    "TEST_WEIGHT",
    "MOISTURE",
    "DAMAGED_TOTAL",
    "HEAT_DAMAGED",
    "FOREIGN_MATERIAL",
]


# --------------------------------------------------------------------------- #
# Reusable factor sets
# --------------------------------------------------------------------------- #

# Rounds to 56.0 / 13.0 / 2.0 / 0.1 / 1.5 — a clean corn US_NO_1 with NONE.
CORN_NO_1_FACTORS = {
    "test_weight_lbs_per_bushel": 56.0,
    "moisture_pct": 13.0,
    "damaged_total_pct": 2.0,
    "heat_damaged_pct": 0.1,
    "foreign_material_pct": 1.5,
}

# Rounds to 56.0 / 12.8 / 2.0 / 0.1 / 1.5 — corn US_NO_1 whose official
# moisture is 12.8, used by the protein basis reconciliation scenarios.
CORN_NO_1_FACTORS_MOISTURE_12_8 = {
    "test_weight_lbs_per_bushel": 56.0,
    "moisture_pct": 12.8,
    "damaged_total_pct": 2.0,
    "heat_damaged_pct": 0.1,
    "foreign_material_pct": 1.5,
}

# Rounds to 55.2 / 14.0 / 4.0 / 0.2 / 2.5 — corn US_NO_2 limited by TEST_WEIGHT.
CORN_NO_2_FACTORS = {
    "test_weight_lbs_per_bushel": 55.2,
    "moisture_pct": 14.04,
    "damaged_total_pct": 4.0,
    "heat_damaged_pct": 0.15,
    "foreign_material_pct": 2.5,
}

# Rounds to 53.9 / 16.2 / 6.4 / 0.4 / 3.9 — corn US_NO_3 limited by TEST_WEIGHT.
CORN_NO_3_FACTORS = {
    "test_weight_lbs_per_bushel": 53.9,
    "moisture_pct": 16.2,
    "damaged_total_pct": 6.4,
    "heat_damaged_pct": 0.44,
    "foreign_material_pct": 3.9,
}

# Rounds to 56.0 / 14.0 / 3.0 / 0.1 / 2.0 — corn US_NO_1 at every table limit.
CORN_NO_1_AT_14_04_MOISTURE = {
    "test_weight_lbs_per_bushel": 56.0,
    "moisture_pct": 14.04,
    "damaged_total_pct": 3.0,
    "heat_damaged_pct": 0.1,
    "foreign_material_pct": 2.0,
}

# Rounds to 56.0 / 14.1 / 3.0 / 0.1 / 2.0 — the same lot one hundredth wetter,
# which rounds up past the corn US_NO_1 moisture limit.
CORN_NO_2_AT_14_05_MOISTURE = {
    "test_weight_lbs_per_bushel": 56.0,
    "moisture_pct": 14.05,
    "damaged_total_pct": 3.0,
    "heat_damaged_pct": 0.1,
    "foreign_material_pct": 2.0,
}

# Rounds to 55.0 / 13.0 / 2.5 / 0.3 / 1.4 — soybean US_NO_2 by TEST_WEIGHT.
SOYBEANS_NO_2_FACTORS = {
    "test_weight_lbs_per_bushel": 55.0,
    "moisture_pct": 12.95,
    "damaged_total_pct": 2.5,
    "heat_damaged_pct": 0.3,
    "foreign_material_pct": 1.4,
}


# --------------------------------------------------------------------------- #
# Reusable draft lists
# --------------------------------------------------------------------------- #

# Six corn drafts with gross-nets of 33700, 33900, 34100, 34300, 34500 and
# 34700 pounds. At a dockage_pct of 1.5 the per-draft route yields a
# dockage_lbs of 3081 and a net_lbs of 202119, while the aggregate route
# deducts 3078 from 205200 for a provisional_net_lbs of 202122.
SIX_CORN_DRAFTS = [
    {"gross_lbs": 55000, "tare_lbs": 21300},
    {"gross_lbs": 55000, "tare_lbs": 21100},
    {"gross_lbs": 55200, "tare_lbs": 21100},
    {"gross_lbs": 55300, "tare_lbs": 21000},
    {"gross_lbs": 55500, "tare_lbs": 21000},
    {"gross_lbs": 55700, "tare_lbs": 21000},
]

SIX_CORN_DRAFTS_DOCKAGE_PCT = 1.5
SIX_CORN_DRAFTS_DOCKAGE_LBS = 3081
SIX_CORN_DRAFTS_NET_LBS = 202119
SIX_CORN_DRAFTS_PROVISIONAL_NET_LBS = 202122
SIX_CORN_DRAFTS_ROUNDING_VARIANCE_LBS = 3
SIX_CORN_DRAFTS_NET_BUSHELS = 3609.27

# A single corn draft with a gross-net of 28000 pounds and no dockage:
# 28000 / 56 = 500.00 bushels exactly.
SINGLE_CORN_DRAFT_500_BU = [{"gross_lbs": 30000, "tare_lbs": 2000}]
SINGLE_CORN_DRAFT_500_BU_NET_BUSHELS = 500.0


TEST_DEFAULTS = {
    "AREA_NAME_DESIGNATED": "Gulf Designated Office",
    "AREA_NAME_DELEGATED": "Plains Delegated Office",
    "AREA_NAME_SECOND": "Lakes Delegated Office",
    "SAMPLING_DEVICE_MODEL": "Diverter D2",
    "SCALE_MODEL": "HopperMax 400",
    "PROTEIN_INSTRUMENT_MODEL": "SpectraGrain 9",
    "SCALE_CAPACITY_LBS": 400000,
    "SCALE_TOLERANCE_LBS": 20.0,
    "SCALE_TEST_ERROR_LBS": 5.0,
    "COURSE_CODE": "GIPSA-CORE",
}

# A syntactically valid UUID that never names a persisted row.
UNKNOWN_UUID = "00000000-0000-4000-8000-000000000001"
UNKNOWN_UUID_ALT = "11111111-2222-3333-4444-555555555555"
MALFORMED_ID = "not-a-uuid"

ALL_ENDORSEMENTS = ["SAMPLING", "GRADING", "PROTEIN", "WEIGHING", "SUPERVISION"]
