"""Domain thresholds — numeric constants from the PRD's calculation narratives."""

# Logical clock startup default (PRD: "The Logical Clock and Lazy Fumigation
# Clearance" — clock starts at exactly 2026-05-01T00:00:00Z before any client
# sets it).
CLOCK_DEFAULT_ISO = "2026-05-01T00:00:00Z"

THRESHOLDS = {
    # Standard moisture level (percent) used by drying-flag derivation,
    # provisional kernel estimate, and settlement moisture deduction.
    "MOISTURE_STD_PCT": 8.0,
    # Provisional estimate shrink: one percent per full moisture point above standard.
    "SHRINK_PER_MOISTURE_POINT": 0.01,
    # Aflatoxin action level (ppb): at or above is FAIL.
    "AFLATOXIN_LIMIT_PPB": 20.0,
    # Premium grade bar on edible_kernel_pct (inclusive).
    "PREMIUM_GRADE_PCT": 0.70,
    # Settlement moisture deduction rate of base per excess moisture point.
    "DEDUCT_PER_MOISTURE_POINT": 0.005,
}

TEST_DEFAULTS = {
    "BASE_PRICE_CENTS_PER_LB": 250,
    "GROSS_WEIGHT_LBS": 5000,
    "BIN_CAPACITY_LBS": 5000,
    "DRYER_CAPACITY_LBS": 60000,
}
