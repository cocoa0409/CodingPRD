"""Domain thresholds and shared values — numeric constants from the PRD."""

# Fixed startup reading of the logical clock (PRD section on the logical clock:
# "At server startup the logical clock reads exactly `2026-08-01T00:00:00Z`").
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

# Reference amounts customarily consumed, grams, by product category.
# Both markets share the same reference-amount table (PRD dual-market section).
RACC_G = {
    "BAKED_GOOD": 55,
    "BEVERAGE": 240,
    "CEREAL": 40,
    "SNACK": 30,
    "DAIRY": 170,
    "SAUCE": 30,
    "CONFECTION": 40,
    "FROZEN_DESSERT": 90,
}

# Label-mode ratio bands: ratio = net_weight_g / racc_g.
DUAL_COLUMN_MIN_RATIO = 2.0
DUAL_COLUMN_MAX_RATIO = 3.0

# Per-serving disqualifier limits (strictly greater disqualifies).
DISQUALIFY_FAT_G_PER_SERVING = 13.0
DISQUALIFY_SATFAT_G_PER_SERVING = 4.0
DISQUALIFY_CHOL_MG_PER_SERVING = 60.0
DISQUALIFY_SODIUM_MG_PER_SERVING = 480.0

# Per-RACC claim thresholds (identical in both markets where regulated).
CLAIM_THRESHOLDS = {
    "FAT_FREE": 0.5,      # fat < 0.5
    "LOW_FAT": 3.0,       # fat <= 3.0
    "SUGAR_FREE": 0.5,    # sugar < 0.5
    "LOW_SODIUM": 140,    # sodium <= 140
    "HIGH_FIBER": 5.0,    # fiber >= 5.0
    "LOW_CALORIE": 40,    # kcal <= 40
}

# Claim types the Canadian market does not regulate.
CA_UNREGULATED_CLAIMS = ["SUGAR_FREE", "LOW_CALORIE"]

# Format-compliance tiers (PRD format-check paragraph).
SMALL_PACKAGE_AREA_SQ_IN = 12.0
MID_PACKAGE_AREA_SQ_IN = 40.0
SMALL_PDP_AREA_SQ_IN = 5.0
MIN_TYPE_SMALL_PDP_IN = 0.03125
MIN_TYPE_LARGE_PDP_IN = 0.0625

# Audit conformance scoring weights (PRD audit close paragraph).
AUDIT_W_CRITICAL = 10
AUDIT_W_MAJOR = 4
AUDIT_W_MINOR = 1
AUDIT_PASS_THRESHOLD_WEIGHTED = 90

# Facility scheduling buffer (PRD time-window semantics).
FACILITY_BUFFER_SECONDS = 86400
