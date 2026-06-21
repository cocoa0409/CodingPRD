"""Domain thresholds and constants from the PRD (PRD §2.3, §3.3, §3.7)."""

# Pagination (PRD §2.3)
PAGINATION = {
    "DEFAULT_LIMIT": 10,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
    "DEFAULT_OFFSET": 0,
}

# Contribution base / catch-up limits in cents (PRD §3.3)
BASE_LIMIT_CENTS = {
    2024: 700_000,
    2025: 700_000,
    2026: 750_000,
}

CATCH_UP_CENTS = {
    2024: 100_000,
    2025: 100_000,
    2026: 110_000,
}

# Catch-up age threshold (PRD §3.3): owner at least 50 years old at year-end.
CATCH_UP_AGE = 50

# RMD age threshold (PRD §3.7): owner at least 73 years old at year-end.
RMD_AGE = 73

# Roth modified-AGI phase-out brackets in cents, keyed by tax_year and filing_status (PRD §3.3).
ROTH_PHASEOUT = {
    2024: {
        "SINGLE": (14_600_000, 16_100_000),
        "MARRIED_JOINT": (23_000_000, 24_000_000),
        "MARRIED_SEPARATE": (0, 1_000_000),
        "HEAD_OF_HOUSEHOLD": (14_600_000, 16_100_000),
    },
    2025: {
        "SINGLE": (15_000_000, 16_500_000),
        "MARRIED_JOINT": (23_600_000, 24_600_000),
        "MARRIED_SEPARATE": (0, 1_000_000),
        "HEAD_OF_HOUSEHOLD": (15_000_000, 16_500_000),
    },
    2026: {
        "SINGLE": (15_400_000, 16_900_000),
        "MARRIED_JOINT": (24_200_000, 25_200_000),
        "MARRIED_SEPARATE": (0, 1_000_000),
        "HEAD_OF_HOUSEHOLD": (15_400_000, 16_900_000),
    },
}

# Roth allowance floor: floor to nearest multiple of 1000 cents (PRD §3.3).
ROTH_FLOOR_CENTS = 1000

# Uniform Lifetime divisor table — values stored in basis-point form (PRD §3.7).
# The integer 2660 represents the decimal divisor 26.60.
UNIFORM_LIFETIME_DIVISOR_BP = {
    73: 2660,
    74: 2580,
    75: 2490,
    76: 2410,
    77: 2320,
    78: 2240,
    79: 2150,
    80: 2070,
    81: 1980,
    82: 1900,
    83: 1820,
    84: 1730,
    85: 1650,
}

# SECURE Act ten-year rule (PRD §3.6, §3.7).
SECURE_YEARS = 10

# Beneficiary share total in basis points (PRD §3.6): sum across ACTIVE designations == 10000.
BENEFICIARY_TOTAL_BPS = 10_000

# Form 1099-R distribution codes (PRD §3.4, §3.9).
FORM_1099R_CODES = {"1", "2", "4", "7", "G", "B", "J", "T"}

# Beneficiary relationship exempt from the SECURE 10-year rule (PRD §3.6).
SECURE_EXEMPT_RELATIONSHIPS = {
    "SPOUSE",
    "MINOR_CHILD",
    "DISABLED",
    "CHRONIC_ILL",
    "ELIGIBLE_TRUST",
}
