"""Domain thresholds — numeric constants from the PRD's calculation rules."""

# Estimate provisional total (PRD §3.2): tiered discount keyed on pre-discount subtotal.
TIER1_MIN_CENTS = 500000      # subtotal at or above this earns 3%
TIER1_PCT = 3
TIER2_MIN_CENTS = 2000000     # subtotal at or above this earns 5%
TIER2_PCT = 5

# Finishing flat fees (PRD §3.2)
FEE_PERF_CENTS = 18000
FEE_SCORE_CENTS = 12000
FEE_UV_COAT_CENTS = 40000
FEE_LAMINATE_CENTS = 55000
FEE_FOIL_CENTS = 75000
FEE_DIE_CUT_CENTS = 60000

# Presort waterfall (PRD §3.9)
FIVE_DIGIT_RATE_CENTS = 24
THREE_DIGIT_RATE_CENTS = 28
AADC_RATE_CENTS = 31
TIER_MINIMUM_PIECES = 150
GLOBAL_MINIMUM_PIECES = 500
MAIL_DAILY_CAPACITY_PIECES = 100000

# Proof overage (PRD §3.12)
PROOF_ROUND_FEE_CENTS = 12500

# Default logical clock at startup (PRD §2.5)
CLOCK_START_ISO = "2026-08-01T00:00:00Z"

# Common scenario values reused across fixtures
STOCK_COST_CENTS = 9
PRESS_IPH = 10000
PRESS_MR_MINUTES = 45
PRESS_WASHUP_MINUTES = 30
RUN_START_ISO = "2026-08-10T08:00:00Z"
DUE_DATE_ISO = "2026-08-20T00:00:00Z"
DROP_DATE = "2026-08-25"

# Liability percentages allowed at claim approve (PRD §3.14)
LIABILITY_PCTS = (25, 50, 100)

# Gang rules (PRD §3.7)
GANG_MIN_MEMBERS = 2
GANG_MAX_MEMBERS = 6
GANG_DUE_WINDOW_DAYS = 3
