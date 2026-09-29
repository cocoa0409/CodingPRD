"""Domain thresholds and rate constants stated in the PRD."""

# --- vulnerability priority score -------------------------------------------
INCOME_POINTS = {
    "ELI": 40,
    "VLI": 30,
    "LOW": 20,
    "MODERATE": 10,
    "ABOVE": 0,
}
HOUSEHOLD_POINT_PER_EXTRA_MEMBER = 4
HOUSEHOLD_POINT_CAP = 20
DISABILITY_POINTS = 15
ELDER_POINTS = 10
ELDER_AGE_THRESHOLD = 65
UNINSURED_POINTS = 15
SCORE_CEILING = 100

# --- per-category damage ceilings (cents) -----------------------------------
CATEGORY_CAP_CENTS = {
    "STRUCTURE": 12_000_000,
    "ROOF": 3_500_000,
    "HVAC": 1_200_000,
    "PLUMBING": 900_000,
    "ELECTRICAL": 900_000,
    "CONTENTS": 1_500_000,
    "ACCESSIBILITY": 2_500_000,
}

# --- purpose buckets --------------------------------------------------------
BUCKET_ORDER = [
    "STRUCTURE_REPAIR",
    "CONTENTS_REPLACEMENT",
    "ACCESSIBILITY_MOD",
    "TEMPORARY_HOUSING",
]
BUCKET_OF_CATEGORY = {
    "STRUCTURE": "STRUCTURE_REPAIR",
    "ROOF": "STRUCTURE_REPAIR",
    "HVAC": "STRUCTURE_REPAIR",
    "PLUMBING": "STRUCTURE_REPAIR",
    "ELECTRICAL": "STRUCTURE_REPAIR",
    "CONTENTS": "CONTENTS_REPLACEMENT",
    "ACCESSIBILITY": "ACCESSIBILITY_MOD",
}

# --- duplication of benefits -------------------------------------------------
DOB_FLAG_THRESHOLD_CENTS = 0
DOB_COUNTED_DOCUMENTATION_STATUSES = ["DOCUMENTED", "DISPUTED"]

# --- restricted-fund waterfall ----------------------------------------------
ADMIN_RETENTION_BPS = 350
ELIGIBLE_PURPOSES_BY_RESTRICTION = {
    "UNRESTRICTED": [
        "STRUCTURE_REPAIR",
        "CONTENTS_REPLACEMENT",
        "ACCESSIBILITY_MOD",
        "TEMPORARY_HOUSING",
    ],
    "STRUCTURE_REPAIR_ONLY": ["STRUCTURE_REPAIR"],
    "CONTENTS_ONLY": ["CONTENTS_REPLACEMENT"],
    "ACCESSIBILITY_ONLY": ["ACCESSIBILITY_MOD"],
    "TEMPORARY_HOUSING_ONLY": ["TEMPORARY_HOUSING"],
    "MATERIALS_ONLY": ["STRUCTURE_REPAIR"],
}
RESTRICTION_SPECIFICITY = {
    "UNRESTRICTED": 0,
    "STRUCTURE_REPAIR_ONLY": 1,
    "CONTENTS_ONLY": 1,
    "ACCESSIBILITY_ONLY": 1,
    "TEMPORARY_HOUSING_ONLY": 1,
    "MATERIALS_ONLY": 1,
}

# --- table award assembly ---------------------------------------------------
TIER_A_CEILING_CENTS = 500_000
TIER_B_CEILING_CENTS = 2_500_000
BRIDGE_PCT_BPS = {"TIER_A": 5000, "TIER_B": 3000, "TIER_C": 1500}
MAX_DEFERRALS = 3

# --- volunteer skill fit ----------------------------------------------------
VOLUNTEER_HOURS_PER_DAY = 6
CRITICAL_TRADE_WEIGHT = 3
NORMAL_TRADE_WEIGHT = 1
MIN_FIT_BPS = 6000
DEPLOYMENT_TURNAROUND_DAYS = 1

# --- pagination -------------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100

# --- logical clock ----------------------------------------------------------
CLOCK_DEFAULT_UTC = "2026-08-01T00:00:00Z"
CLOCK_TEST_UTC = "2026-09-01T00:00:00Z"

# --- values recurring across test setups ------------------------------------
TEST_DEFAULTS = {
    "DISASTER_CODE": "DR-4801",
    "CASE_MANAGER_USER_ID": "u_cm_1",
}


def round_half_up_bps(numerator: int, denominator: int) -> int:
    """Ten thousand times numerator/denominator, rounded half up."""
    if denominator == 0:
        return 10000
    return (2 * 10000 * numerator + denominator) // (2 * denominator)


def retention_cents(net_cents: int) -> int:
    """Administrative retention on a single allocation line, rounded half up."""
    return (2 * net_cents * ADMIN_RETENTION_BPS + 10000) // 20000
