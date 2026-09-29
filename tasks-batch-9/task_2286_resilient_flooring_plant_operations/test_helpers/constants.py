"""Thresholds, factors and boundary values quoted from the PRD.

Nothing here is invented: every value is stated in the PRD section named in the
comment beside it. Tests import these so that a boundary is written once and a
test reads as "exactly at the declared threshold" rather than as a bare number.
"""

# --- Identity and pagination (PRD 2.2, 2.3) --------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# A syntactically valid UUID that is guaranteed to match no stored row.
NON_EXISTENT_UUID = "00000000-0000-4000-8000-000000000000"

# --- Logical clock (PRD 2.4) ----------------------------------------------
# "the clock starts at 2026-08-01T00:00:00Z when the system boots"
CLOCK_BOOT_UTC = "2026-08-01T00:00:00Z"

# --- Money and rates (PRD 2.6) -------------------------------------------
# "A rate in basis points is applied by multiplying by the rate and dividing by
# 10000".
BPS_DENOMINATOR = 10000

# --- Blend metrics (PRD 3.1) ---------------------------------------------
RESIN_PHR_NORMALIZED = 100.00
BLEND_INDEX_DECIMALS = 6
INDENTATION_INDEX_WEIGHT = 0.40
THERMAL_INDEX_WEIGHT = 0.35
MIGRATION_INDEX_WEIGHT = 0.25
SOFTNESS_PENALTY_HIGH = 12  # ratio > 0.35
SOFTNESS_PENALTY_LOW = 5  # 0.25 < ratio <= 0.35
SOFTNESS_RATIO_HIGH = 0.35
SOFTNESS_RATIO_LOW = 0.25
BRITTLENESS_PENALTY_HIGH = 8  # ratio >= 3.00
BRITTLENESS_PENALTY_LOW = 3  # 2.00 <= ratio < 3.00
BRITTLENESS_RATIO_HIGH = 3.00
BRITTLENESS_RATIO_LOW = 2.00
# "The `performance_score` must be at least 60.00 ... a score of exactly 60.00
# is approvable because the threshold is inclusive."
MIN_PERFORMANCE_SCORE = 60.00
# "the class is `CLASS_34_43` when that index is at least 88.00, `CLASS_33_42`
# when it is at least 70.00 but below 88.00, and `CLASS_23_31` otherwise."
INDENTATION_CLASS_34_43_FLOOR = 88.00
INDENTATION_CLASS_33_42_FLOOR = 70.00

# --- Design grants (PRD 3.2) ---------------------------------------------
MIN_ROYALTY_RATE_BPS = 0
MAX_ROYALTY_RATE_BPS = 2000
MIN_MASTER_ROLL_SETS = 1

# --- SKU definition, warranty terms and standard cost (PRD 3.3) ----------
MAX_WEAR_LAYER_MIL = 40
MAX_OVERALL_THICKNESS_MM = 12
DEFAULT_TARGET_MARGIN_BPS = 3500
MIN_TARGET_MARGIN_BPS = 0
MAX_TARGET_MARGIN_BPS = 9000
# "the two tolerances added together may not exceed 0.50 millimetres"
MAX_TOLERANCE_BAND_SUM_MM = 0.50

# Warranty tiers, inclusive thresholds on wear_layer_mil.
WARRANTY_TIER_TOP_MIL = 20
WARRANTY_TIER_MID_MIL = 12
WARRANTY_TIER_LOW_MIL = 6
RESIDENTIAL_WARRANTY_YEARS = {"top": 25, "mid": 20, "low": 15, "base": 10}
LIGHT_COMMERCIAL_WARRANTY_YEARS = {"top": 15, "mid": 10, "low": 5, "base": 0}
WATERPROOF_CLICK_LOCK_BONUS_YEARS = 5
RESIDENTIAL_WARRANTY_CAP_YEARS = 30
LIGHT_COMMERCIAL_WARRANTY_CAP_YEARS = 20

# Standard cost components.
SPECIFIC_GRAVITY_KG_PER_SQM_PER_MM = 1.90
WEAR_LAYER_CENTS_PER_MIL = 3.5
PRINT_FILM_BASE_CENTS = 18
PRINT_FILM_REPEAT_SURCHARGE_LARGE_CENTS = 6  # larger repeat >= 1800 mm
PRINT_FILM_REPEAT_SURCHARGE_MEDIUM_CENTS = 2  # 1200 mm <= larger repeat < 1800
PRINT_FILM_REPEAT_LARGE_MM = 1800
PRINT_FILM_REPEAT_MEDIUM_MM = 1200
UNDERLAYMENT_COST_CENTS = {
    "NONE": 0,
    "IXPE_1MM": 22,
    "EVA_1_5MM": 17,
    "CORK_2MM": 41,
}
WATERPROOF_COST_CENTS = 9
CONVERSION_BASE_CENTS = 35
CLICK_LOCK_MILLING_CENTS = 12

# --- Laboratory (PRD 3.4) ------------------------------------------------
# "a marginal band of 500 basis points -- five percent -- on the permissive
# side of the limit."
MARGINAL_BAND_BPS = 500
LOWER_IS_BETTER_MARGINAL_FACTOR = 1.05
HIGHER_IS_BETTER_MARGINAL_FACTOR = 0.95
RESIDUAL_INDENTATION_LIMITS = {
    "CLASS_34_43": 0.10,
    "CLASS_33_42": 0.20,
    "CLASS_23_31": 0.30,
}
DIMENSIONAL_STABILITY_LIMIT_CLICK_LOCK = 0.15
DIMENSIONAL_STABILITY_LIMIT_OTHER = 0.25
SLIP_RESISTANCE_LIMIT_WATERPROOF = 0.42
SLIP_RESISTANCE_LIMIT_OTHER = 0.36
PEEL_ADHESION_LIMITS = {"IXPE_1MM": 35.0, "EVA_1_5MM": 30.0, "CORK_2MM": 45.0}
# "A restart is refused with ERR_RETEST_LIMIT_EXCEEDED once `retest_count` has
# passed the two permitted retests -- that is, once `retest_count` is greater
# than 2".
MAX_PERMITTED_RETESTS = 2
BASE_REQUIRED_TEST_TYPES = ["RESIDUAL_INDENTATION", "DIMENSIONAL_STABILITY_HEAT"]
CANONICAL_TEST_TYPE_ORDER = [
    "RESIDUAL_INDENTATION",
    "DIMENSIONAL_STABILITY_HEAT",
    "SLIP_RESISTANCE",
    "PEEL_ADHESION_DELAMINATION",
    "LOCK_SHEAR",
]

# --- Scheduling and completion (PRD 3.6) ---------------------------------
# "the logical clock must have reached `planned_start_utc` minus 120 minutes"
SETUP_LEAD_MINUTES = 120
# "whose `updated_at` is strictly later than the logical clock minus 180 days"
SLIP_QUALIFICATION_WINDOW_DAYS = 180
CHANGEOVER_MULTIPLIER_SAME_FORMULATION = 0.50
CHANGEOVER_MULTIPLIER_SAME_PRINT_FILM = 0.75
CHANGEOVER_MULTIPLIER_UNRELATED = 1.00
THICKNESS_SURCHARGE_LARGE_MINUTES = 30  # delta >= 2.0 mm
THICKNESS_SURCHARGE_SMALL_MINUTES = 10  # 0.5 mm <= delta < 2.0 mm
THICKNESS_SURCHARGE_LARGE_MM = 2.0
THICKNESS_SURCHARGE_SMALL_MM = 0.5
PATTERN_WASTE_DIVISOR = 60000
PATTERN_WASTE_FACTOR = 0.35
EMBOSS_TOLERANCE_MM = 0.30
CURL_ALLOWANCE_BASE_MM = 2.00

# --- Batches (PRD 3.7) --------------------------------------------------
BATCH_CODE_SUFFIX = "-B1"
HOLD_REASON_SKU_ON_HOLD = "SKU_ON_HOLD"
HOLD_REASON_QC_QUARANTINE = "QC_QUARANTINE"
CASCADE_HELD_BY_USER_ID = "system"

# --- Distributors and allocations (PRD 3.8) -----------------------------
MIN_ACCOUNT_CODE_LENGTH = 3
MAX_ACCOUNT_CODE_LENGTH = 32
TERRITORY_CODE_LENGTH = 2

# --- Warranty settlement (PRD 3.9) --------------------------------------
MONTHS_PER_YEAR = 12
LABOR_ALLOWANCE_CENTS_PER_SQM = 350
# "100 percent when that figure is 1 or less, 80 percent when it is 2 or 3, 60
# percent when it is 4 through 7, 40 percent when it is 8 through 12, and 20
# percent beyond that"
STEPPED_SCHEDULE_PERCENTS = [
    (1, 100),
    (3, 80),
    (7, 60),
    (12, 40),
    (None, 20),
]
# "the batch's `wear_layer_measured_mil` is strictly less than the SKU's
# specified `wear_layer_mil` minus 0.5 mil"
MANUFACTURING_DEFECT_TOLERANCE_MIL = 0.5
