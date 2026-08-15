"""Domain thresholds and constants from the PRD's pricing and agronomy rules."""

# Logical clock startup default (PRD §2.4): before any client intervention the
# server-side logical clock reads exactly this instant.
STARTUP_CLOCK_UTC = "2026-08-01T00:00:00Z"

# Early-order rule (PRD §3.5): orders smaller than this many total units earn
# no early-order discount.
MIN_ORDER_UNITS_FOR_DISCOUNT = 20

# Basis points (PRD §2.6): 10000 basis points equal 100 percent.
BPS_DENOMINATOR = 10000

# Placement score weights (PRD §3.4): soil 0.35, drainage 0.25, maturity 0.25,
# rotation 0.15, rendered with one decimal place rounded half-up.
PLACEMENT_WEIGHTS = {
    "W_SOIL": 0.35,
    "W_DRAINAGE": 0.25,
    "W_MATURITY": 0.25,
    "W_ROTATION": 0.15,
}

# Drainage ranks used wherever drainage comparisons are needed (PRD §3.2/§3.4):
# POOR = 1, MODERATE = 2, WELL = 3.
DRAINAGE_RANK = {"POOR": 1, "MODERATE": 2, "WELL": 3}

# Maturity-fit bands (PRD §3.4): gap of five days or fewer -> 1; greater than
# five but no more than fifteen -> 0.5; larger -> 0.
MATURITY_FIT_FULL_GAP_DAYS = 5
MATURITY_FIT_PARTIAL_GAP_DAYS = 15

TEST_DEFAULTS = {
    "VARIETY_PRICE_CENTS": 18000,
    "CREDIT_LIMIT_CENTS": 100000000,
    "LOT_RECEIVED_UNITS": 500,
}
