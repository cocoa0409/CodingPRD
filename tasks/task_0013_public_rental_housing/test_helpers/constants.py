"""Domain thresholds and computational constants from PRD §3.

These mirror the numeric values used in the Public Rental Housing API formulas. They are
imported by tests when boundary precision matters (so test arithmetic stays in lockstep
with PRD prose) and by fixtures when defaulting program parameters.
"""

# ──────────────────────────────────────────────────────────
# Queue score (PRD §3.3)
# ──────────────────────────────────────────────────────────

HOUSEHOLD_TYPE_PTS = {
    "LOW_INCOME": 30,
    "NEW_CITIZEN": 15,
    "RELOCATION": 20,
    "TALENT": 25,
}

DISABILITY_PTS = 20  # PRD §3.3: contributes 20 if at least one member has has_disability true

SPECIAL_CARE_PTS = {
    "NONE": 0,
    "VETERAN": 15,
    "MARTYR_FAMILY": 18,
    "SINGLE_PARENT": 10,
    "ELDERLY_LIVE_ALONE": 12,
}

RESIDENCE_PTS_PER_PERIOD = 1
RESIDENCE_PTS_CAP = 20  # PRD §3.3: residence component capped at 20 points

# ──────────────────────────────────────────────────────────
# Rent reduction (PRD §3.6)
# ──────────────────────────────────────────────────────────

# PRD §3.6 — strict less-than tier comparisons.
RENT_REDUCTION_TIER_THRESHOLDS = [0.30, 0.50, 0.80]
RENT_REDUCTION_TIER_BPS = [5000, 3000, 1500, 0]

RENT_REDUCTION_CATEGORY_BOOST_BPS = {
    "MAJOR_ILLNESS": 1500,
    "UNEMPLOYMENT": 1000,
    "DISABILITY": 1500,
    "ELDER_CARE": 500,
}

RENT_REDUCTION_MAX_BPS = 10000  # PRD §3.6: smaller of 10000 and (base + boost)

# Default validity window length (PRD §3.6: validity_end_period = current + 12, half-open).
RENT_REDUCTION_VALIDITY_LENGTH = 12

# ──────────────────────────────────────────────────────────
# Deposit, rent split (PRD §2.7, §3.5, §3.6)
# ──────────────────────────────────────────────────────────

MONTHS_OF_DEPOSIT = 2  # PRD §3.5: deposit = monthly_base_rent_cents * 2 (half-up)
LIVING_ROOM_FRACTION = 0.40  # PRD §3.6: living room takes 40% in non-STUDIO
BEDROOM_FRACTION_TOTAL = 0.60

# ──────────────────────────────────────────────────────────
# Allocation matching tolerance (PRD §3.4)
# ──────────────────────────────────────────────────────────

FAMILY_SIZE_TOLERANCE = {
    "STUDIO": [1],
    "ONE_BEDROOM": [1, 2],
    "TWO_BEDROOM": [2, 3, 4],
    "THREE_BEDROOM": [4, 5, 6, 7],
}

# ──────────────────────────────────────────────────────────
# Test defaults — sensible values used by fixtures unless overridden.
# ──────────────────────────────────────────────────────────

TEST_DEFAULTS = {
    "NOTICE_PERIOD_LENGTH": 3,
    "GRACE_PERIOD_LENGTH": 6,
    "PER_CAPITA_INCOME_THRESHOLD_CENTS": 300_000,
    "PER_CAPITA_ASSET_THRESHOLD_CENTS": 500_000,
    "MONTHLY_BASE_RENT_CENTS": 50_000,
    "DECLARED_MONTHLY_INCOME_CENTS": 200_000,
    "DECLARED_TOTAL_ASSETS_CENTS": 200_000,
    "VERIFIED_MONTHLY_INCOME_CENTS": 200_000,
    "VERIFIED_TOTAL_ASSETS_CENTS": 200_000,
}

# Aggregate alias — some test files reference THRESHOLDS for thematic threshold values.
THRESHOLDS = {
    "RESIDENCE_PTS_CAP": RESIDENCE_PTS_CAP,
    "DISABILITY_PTS": DISABILITY_PTS,
    "RENT_REDUCTION_MAX_BPS": RENT_REDUCTION_MAX_BPS,
    "RENT_REDUCTION_VALIDITY_LENGTH": RENT_REDUCTION_VALIDITY_LENGTH,
    "MONTHS_OF_DEPOSIT": MONTHS_OF_DEPOSIT,
}
