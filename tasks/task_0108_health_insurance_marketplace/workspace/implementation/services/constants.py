"""Domain constants: FPL table, applicable percentage table, age curve, etc."""

# FPL_TABLE: version -> household_size -> denominator_cents
FPL_TABLE = {
    "v1": {
        1: 1525500,
        2: 2067500,
        3: 2609500,
        4: 3151500,
        5: 3693500,
        6: 4235500,
        "per_additional_after_6": 542000,
    },
    "v2": {
        1: 1572500,
        2: 2131000,
        3: 2689500,
        4: 3248000,
        5: 3806500,
        6: 4365000,
        "per_additional_after_6": 558500,
    },
}

# Map coverage_year -> FPL table version
COVERAGE_YEAR_TO_FPL_VERSION = {
    2025: "v1",
    2026: "v2",
}


def fpl_version_for_year(coverage_year: int) -> str:
    """Pick fpl table version for a coverage year; default v2 for years >= 2026."""
    if coverage_year in COVERAGE_YEAR_TO_FPL_VERSION:
        return COVERAGE_YEAR_TO_FPL_VERSION[coverage_year]
    if coverage_year <= 2025:
        return "v1"
    return "v2"


def fpl_denominator(version: str, household_size: int) -> int:
    """Return denominator cents for given fpl version and household size (>=1)."""
    table = FPL_TABLE[version]
    if household_size < 1:
        household_size = 1
    if household_size <= 6:
        return table[household_size]
    return table[6] + table["per_additional_after_6"] * (household_size - 6)


# APPLICABLE_PERCENTAGE_TABLE: half-open [lower, upper) -> fraction
APPLICABLE_PERCENTAGE_TABLE = [
    (100.0, 150.0, 0.0000),
    (150.0, 200.0, 0.0200),
    (200.0, 250.0, 0.0400),
    (250.0, 300.0, 0.0600),
    (300.0, 400.0, 0.0850),
    (400.0, 99999.0, 1.0000),
]


def applicable_percentage(fpl_pct: float) -> float:
    """Look up the applicable percentage fraction for a given fpl_percentage."""
    for lower, upper, fraction in APPLICABLE_PERCENTAGE_TABLE:
        if lower <= fpl_pct < upper:
            return fraction
    return 0.0


# Age curve multipliers — keyed by lower bound; need to map an age to a bracket.
AGE_BRACKETS = [
    (0, 14, 0.765),
    (15, 20, 0.833),
    (21, 24, 1.000),
    (25, 29, 1.061),
    (30, 34, 1.150),
    (35, 39, 1.181),
    (40, 44, 1.278),
    (45, 49, 1.444),
    (50, 54, 1.706),
    (55, 59, 2.040),
    (60, 63, 2.411),
    (64, 200, 3.000),
]


def age_multiplier(age: int) -> float:
    for low, high, mult in AGE_BRACKETS:
        if low <= age <= high:
            return mult
    # Fallback for negative or weird ages
    return 0.765 if age < 0 else 3.000


TOBACCO_SURCHARGE = 1.50


# Medicaid expansion table for all 51 jurisdictions (50 states + DC).
# Source: canonical reference — expansion as of 2024.
MEDICAID_EXPANSION = {
    "AL": False, "AK": True,  "AZ": True,  "AR": True,  "CA": True,
    "CO": True,  "CT": True,  "DE": True,  "DC": True,  "FL": False,
    "GA": False, "HI": True,  "ID": True,  "IL": True,  "IN": True,
    "IA": True,  "KS": False, "KY": True,  "LA": True,  "ME": True,
    "MD": True,  "MA": True,  "MI": True,  "MN": True,  "MS": False,
    "MO": True,  "MT": True,  "NE": True,  "NV": True,  "NH": True,
    "NJ": True,  "NM": True,  "NY": True,  "NC": True,  "ND": True,
    "OH": True,  "OK": True,  "OR": True,  "PA": True,  "RI": True,
    "SC": False, "SD": True,  "TN": False, "TX": False, "UT": True,
    "VT": True,  "VA": True,  "WA": True,  "WV": True,  "WI": False,
    "WY": False,
}


VALID_STATES = set(MEDICAID_EXPANSION.keys())


VALID_FILER_TYPES = {"PRIMARY_FILER", "SPOUSE", "DEPENDENT"}
VALID_INCOME_SOURCES = {"WAGES", "SELF_EMPLOYMENT", "SOCIAL_SECURITY",
                        "INTEREST_DIVIDEND", "RETIREMENT", "RENTAL", "OTHER"}
VALID_TIERS = {"BRONZE", "SILVER", "GOLD", "PLATINUM"}
VALID_CSR_LEVELS = {"STANDARD", "CSR_73", "CSR_87", "CSR_94", "CSR_PLUS"}
VALID_SEP_EVENT_TYPES = {"LOSS_OF_COVERAGE", "MARRIAGE", "BIRTH_ADOPTION",
                         "MOVE", "INCOME_CHANGE", "MEDICAID_LOSS", "GAINED_CITIZENSHIP"}
