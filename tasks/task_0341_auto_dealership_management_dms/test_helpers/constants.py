"""Domain thresholds — numeric constants from the PRD's calculations."""

# Provisional desking estimate rate/term (PRD §3.4 Monthly payment, ESTIMATE variant).
DESK_ESTIMATE_RATE_BPS = 699
DESK_ESTIMATE_TERM_MONTHS = 72

# Floor-plan payoff day-count basis (PRD §3.1 payoff quote).
DAY_COUNT_BASIS = 360

# Finance reserve tier (PRD §3.4 Finance reserve).
MARKUP_TIER_BPS = 150
RESERVE_RATE_LOW = 0.01
RESERVE_RATE_HIGH = 0.02

# Curtailment aging threshold (PRD §3.1 curtailments).
CURTAILMENT_AGE_DAYS = 90
CURTAILMENT_PCT = 0.10

BASIS_POINTS_DIVISOR = 10000

# Common test defaults reused across fixtures.
TEST_DEFAULTS = {
    "TIER_A_BUY_RATE_BPS": 549,
    "MAX_MARKUP_BPS": 200,
    "MAX_LTV_BPS": 12500,
    "MAX_PTI_BPS": 1800,
    "MAX_TERM_MONTHS": 72,
    "FLOOR_RATE_BPS": 825,
    "TAX_RATE_BPS": 725,
}
