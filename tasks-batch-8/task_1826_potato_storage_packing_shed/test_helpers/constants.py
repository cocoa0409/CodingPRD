"""Domain thresholds — numeric constants from PRD calculations (§3.4, §3.7, §3.9)."""

THRESHOLDS = {
    # wash-water check result bounds (PRD §3.7)
    "WASH_MAX_TURBIDITY_NTU": 4.0,
    "QUARANTINE_TURBIDITY_NTU": 8.0,
    "CHLORINE_MIN_PPM": 50,
    "CHLORINE_MAX_PPM": 200,
    "WASH_TEMP_MIN_F": 45,
    "WASH_TEMP_MAX_F": 60,
    "RESTRICTED_CONSECUTIVE_FAILS": 2,
    "WASH_VALIDITY_HOURS_NORMAL": 12,
    "WASH_VALIDITY_HOURS_RESTRICTED": 4,
    # sprout-inhibitor retreat window in days (PRD §3.2)
    "RETREAT_WINDOW_DAYS": 21,
    # manual lot close remnant ceiling in cwt (PRD §3.2)
    "REMNANT_MAX_CWT": 5.0,
    # default expected packout fraction (PRD §3.4)
    "DEFAULT_BLEND_PACKOUT_FRACTION": 0.75,
}

FEES = {
    # PRD §3.9 settlement rates
    "STORAGE_FEE_CENTS_PER_CWT_WEEK": 12.5,
    "INHIBITOR_FEE_CENTS_PER_CWT": 8,
    "PROCESSING_CREDIT_CENTS_PER_CWT": 150,
}

# The logical clock starts here before any admin intervention (PRD §2.5).
CLOCK_START_ISO = "2026-08-01T00:00:00Z"

TEST_DEFAULTS = {
    "HARVEST_DATE": "2026-07-20",
    "PACK_UNIT_WEIGHT_LBS": 50,
    "GRADE_MIN_US1_PCT": 50.0,
    "WINDOW_START": "2026-08-01T00:00:00Z",
    "WINDOW_END": "2026-12-01T00:00:00Z",
}
