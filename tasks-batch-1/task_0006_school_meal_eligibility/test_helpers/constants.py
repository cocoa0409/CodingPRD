"""Domain thresholds and constants from the PRD's calculations and validation rules."""

# Tier-determination percentages (PRD §3.3).
FREE_PCT = 1.30          # household_monthly <= 130% of FPL_MONTHLY => FREE
REDUCED_PCT = 1.85       # 130% < household_monthly <= 185% => REDUCED


# Federal poverty monthly tables (whole dollars/month), by family_size (PRD §3.3).
FPL_MONTHLY_CONTIGUOUS = {
    1: 1255, 2: 1704, 3: 2152, 4: 2600,
    5: 3049, 6: 3497, 7: 3946, 8: 4394,
}
FPL_MONTHLY_ALASKA = {
    1: 1569, 2: 2129, 3: 2690, 4: 3251,
    5: 3811, 6: 4372, 7: 4933, 8: 5494,
}
FPL_MONTHLY_HAWAII = {
    1: 1443, 2: 1960, 3: 2476, 4: 2993,
    5: 3509, 6: 4026, 7: 4543, 8: 5059,
}


# Reduced-tier discount (PRD §3.5).
REDUCED_DISCOUNT_FACTOR = 0.10
REDUCED_PRICE_CAP_CENTS = 40
ALLERGEN_SUB_SURCHARGE_CENTS = 25


# Daily top-up cap (PRD §3.6).
DAILY_TOPUP_CAP_CENTS = 20000   # $200 per UTC calendar day


# Common ISO 8601 UTC clock anchors used by fixtures. Tests pin the server
# clock at start of run; these are deterministic anchors used across multiple
# scenarios.
DEFAULT_CLOCK_ISO = "2026-01-15T12:00:00.000Z"
SCHOOL_YEAR_LABEL_DEFAULT = "2025-2026"
DEFAULT_VALID_FROM = "2026-01-01T00:00:00.000Z"
DEFAULT_VALID_TO = "2026-08-31T23:59:59.000Z"


# Allergen enum values (PRD §3.1).
ALLERGEN_VALUES = (
    "PEANUT", "TREE_NUT", "MILK", "EGG", "SOY", "WHEAT", "FISH", "SHELLFISH",
)
