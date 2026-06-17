"""Domain thresholds — numeric constants from the PRD calculations."""

# Floor-plan loan thresholds (PRD 3.2)
CURTAILMENT_DUE_DAYS = 90
CURTAILMENT_PCT_BPS = 1000          # 10% of original advance
DAYS_PER_YEAR = 365

# Flat-rate labor tiers (PRD 3.7)
BASE_LABOR_RATE_CENTS = 12500       # $125.00/hr retail
TIER1_HOURS = 2.0
TIER2_HOURS = 6.0
TIER2_RATE_CENTS = 11500            # base - 1000 discount, for 2 < hrs <= 6
TIER3_RATE_CENTS = 10000            # base - 2500 discount, for hrs > 6
WARRANTY_LABOR_RATE_CENTS = 9000    # $90.00/hr manufacturer reimbursement
SHOP_SUPPLY_BPS = 800               # 8% of labor
SHOP_SUPPLY_CAP_CENTS = 5000        # $50 cap

# Storage (PRD 3.10)
WINTERIZATION_FEE_CENTS = 14900     # $149.00

# Deal defaults (PRD 3.3)
DEFAULT_DOC_FEE_CENTS = 39900       # $399.00
DEFAULT_TECH_CLEANUP_BUFFER_MINUTES = 30
