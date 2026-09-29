"""Domain thresholds and canonical fixture values taken from the PRD."""

# The logical clock's value before any client sets it (PRD §2.4).
CLOCK_EPOCH = "2026-08-01T00:00:00Z"

THRESHOLDS = {
    # Notice and calendar windows (PRD §3.3)
    "ANNOUNCED_MIN_NOTICE_HOURS": 72.00,
    "AUDITOR_TRAVEL_BUFFER_MINUTES": 60,
    "LOCATION_QUOTA_WINDOW_DAYS": 7,
    "LOCATION_UNANNOUNCED_QUOTA": 2,
    "UNANNOUNCED_MIX_WINDOW_DAYS": 182,
    "VISIT_START_EARLY_MINUTES": 60,
    # Section weighting and penalty ladder (PRD §3.4)
    "WEIGHT_FOOD_SAFETY": 0.50,
    "WEIGHT_BRAND_STANDARDS": 0.30,
    "WEIGHT_FACILITY": 0.20,
    "CRITICAL_PENALTY_ZERO": 0.00,
    "CRITICAL_PENALTY_ONE": 5.00,
    "CRITICAL_PENALTY_TWO": 12.00,
    "CRITICAL_PENALTY_THREE_PLUS": 25.00,
    # Composite variants (PRD §3.4, §3.5)
    "PROVISIONAL_BASE_WEIGHT": 0.60,
    "PROVISIONAL_FOOD_SAFETY_WEIGHT": 0.40,
    "FINAL_BASE_WEIGHT": 0.45,
    "FINAL_FOOD_SAFETY_WEIGHT": 0.30,
    "FINAL_HEALTH_WEIGHT": 0.25,
    # Grade bands (PRD §3.4)
    "GRADE_PASS_MIN": 90.00,
    "GRADE_CONDITIONAL_MIN": 80.00,
    "CRITICAL_FAIL_OVERRIDE_COUNT": 2,
    # Health selection (PRD §3.5)
    "HEALTH_LOOKBACK_DAYS": 180,
    "HEALTH_CAP_A": 100.00,
    "HEALTH_CAP_B": 100.00,
    "HEALTH_CAP_C": 79.00,
    "HEALTH_CAP_FAIL": 0.00,
    # Corrective-action deadlines (PRD §3.5)
    "CRITICAL_DUE_HOURS": 72,
    "STANDARD_DUE_DAYS": 14,
    # Standing score (PRD §3.9)
    "STANDING_WEIGHTS": (0.50, 0.30, 0.20),
    "REPEAT_PENALTY_PER_UNIT_HIGH": 0.50,
    "REPEAT_PENALTY_PER_UNIT_MID": 1.00,
    "REPEAT_PENALTY_PER_UNIT_LOW": 2.00,
    "REPEAT_VIOLATION_LOOKBACK_DAYS": 365,
    "REPEAT_VIOLATION_MIN_VISITS": 2,
    # Reliability and calibration (PRD §3.8)
    "RELIABILITY_BASELINE": 70.00,
    "RELIABILITY_CERTIFICATION_FLOOR": 70.00,
    "RELIABILITY_SUSPENSION_FLOOR": 60.00,
    "RELIABILITY_MIN": 0.00,
    "RELIABILITY_MAX": 100.00,
    "ROLLING_WEIGHTS": (1.00, 0.60, 0.30),
    "BAND_EXCELLENT_MAX_VARIANCE": 2.00,
    "BAND_ACCEPTABLE_MAX_VARIANCE": 5.00,
    "BAND_MARGINAL_MAX_VARIANCE": 10.00,
    "DELTA_EXCELLENT": 4.00,
    "DELTA_ACCEPTABLE": 1.00,
    "DELTA_MARGINAL": -3.00,
    "DELTA_UNACCEPTABLE": -8.00,
    # Brand risk index (PRD §3.9)
    "RISK_DEFICIT_WEIGHT": 0.60,
    "RISK_OPEN_CRITICAL_PER_ACTION": 6.00,
    "RISK_OPEN_CRITICAL_CAP": 40.00,
    "RISK_DEFAULT_PER_LOCATION": 10.00,
    "RISK_DEFAULT_CAP": 30.00,
    "RISK_FAIL_SURCHARGE": 15.00,
    "RISK_INDEX_CAP": 100.00,
    "TIER_SEVERE_MIN": 60.00,
    "TIER_ELEVATED_MIN": 35.00,
    # Counter ceilings (PRD §3.4, §3.7)
    "RESCORE_LIMIT": 2,
    "INFO_REQUEST_LIMIT": 2,
    # Escalation levels (PRD §2.11)
    "LEVEL_GOOD_STANDING": 0,
    "LEVEL_NOTICE_OF_DEFAULT": 1,
    "LEVEL_CURE_PERIOD": 2,
    "LEVEL_TERMINATION_RECOMMENDED": 3,
    # Pagination (PRD §2.3)
    "PAGINATION_DEFAULT_LIMIT": 10,
    "PAGINATION_MIN_LIMIT": 1,
    "PAGINATION_MAX_LIMIT": 100,
}

TEST_DEFAULTS = {
    "BRAND_NAME": "Skewer House",
    "BRAND_CODE": "SKWR",
    "UNANNOUNCED_MIN_RATIO_PCT": 40,
    "FRANCHISEE_LEGAL_NAME": "Northline Foods LLC",
    "FRANCHISEE_CONTACT_EMAIL": "ops@northline.test",
    "AGREEMENT_SIGNED_AT": "2025-03-01T00:00:00Z",
    "STORE_NUMBER": "SKWR-014",
    "REGION_CODE": "MIDWEST",
    "AUDITOR_NAME": "Dana Reyes",
    "AUDITOR_CODE": "AUD-101",
    "REVIEWER_NAME": "Kim Osei",
    "REVIEWER_CODE": "AUD-777",
    "RUBRIC_LABEL": "RV-2026.1",
    "RUBRIC_EFFECTIVE_FROM": "2026-07-01T00:00:00Z",
    "RUBRIC_TOTAL_POINTS": 100,
    "AUTHORITY_NAME": "Cook County DPH",
    "PHOTO_URI": "s3://evidence/brand-standards/photo.jpg",
}

# The canonical six-item rubric used throughout the fixtures: two critical
# FOOD_SAFETY items, two BRAND_STANDARDS items and two FACILITY items whose
# max_points sum to the declared total of 100.
CANONICAL_RUBRIC_ITEMS = [
    {"item_code": "FS-1", "section": "FOOD_SAFETY", "max_points": 30,
     "is_critical": True, "display_order": 1},
    {"item_code": "FS-2", "section": "FOOD_SAFETY", "max_points": 20,
     "is_critical": True, "display_order": 2},
    {"item_code": "BS-1", "section": "BRAND_STANDARDS", "max_points": 15,
     "is_critical": False, "display_order": 3},
    {"item_code": "BS-2", "section": "BRAND_STANDARDS", "max_points": 15,
     "is_critical": False, "display_order": 4},
    {"item_code": "FC-1", "section": "FACILITY", "max_points": 12,
     "is_critical": False, "display_order": 5},
    {"item_code": "FC-2", "section": "FACILITY", "max_points": 8,
     "is_critical": False, "display_order": 6},
]

# Score sheets used by the calculation tests, keyed by item_code.
# Sheet A: exactly one critical violation.
SCORE_SHEET_ONE_CRITICAL = {
    "FS-1": 27, "FS-2": 20, "BS-1": 12, "BS-2": 15, "FC-1": 10, "FC-2": 8,
}
# Sheet B: exactly two critical violations.
SCORE_SHEET_TWO_CRITICAL = {
    "FS-1": 27, "FS-2": 19, "BS-1": 15, "BS-2": 15, "FC-1": 12, "FC-2": 8,
}
# Sheet with no violation at all.
SCORE_SHEET_PERFECT = {
    "FS-1": 30, "FS-2": 20, "BS-1": 15, "BS-2": 15, "FC-1": 12, "FC-2": 8,
}
# Sheet used by a shadow reviewer whose scoring is far enough from the primary
# sheet to land the variance in the widest calibration band.
SCORE_SHEET_SHADOW = {
    "FS-1": 24, "FS-2": 16, "BS-1": 15, "BS-2": 15, "FC-1": 12, "FC-2": 8,
}
# Sheet used by a shadow reviewer whose scoring is very close to the primary
# sheet, so the variance lands in the narrowest calibration band.
SCORE_SHEET_SHADOW_CLOSE = {
    "FS-1": 27, "FS-2": 20, "BS-1": 12, "BS-2": 15, "FC-1": 9, "FC-2": 8,
}
