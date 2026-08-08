"""Domain thresholds — numeric constants from the PRD calculations."""

# County collection/administration fee withheld from gross increment (PRD 3.2).
ADMIN_FEE_RATE = 0.03

# District term is at least 1 and at most 23 tax years (PRD 3.1).
TERM_YEARS_MAX = 23

# ppm scale for surplus shares (PRD 3.6).
PPM_SCALE = 1_000_000

# Convenient default weights: School .05 + County .02 + City .01 = aggregate .08.
DEFAULT_AGGREGATE_TAX_RATE = 0.08

TEST_DEFAULTS = {
    "BASE_TAX_YEAR": 2025,
    "TERM_YEARS": 23,
    "EXPIRATION_TAX_YEAR": 2048,  # base 2025 + term 23
}
