"""Domain thresholds — numeric constants from PRD calculations (PRD §3.2, §3.6, §3.7, §3.11)."""

# KYC risk scoring weights (PRD §3.2)
KYC = {
    "NON_US_WEIGHT": 40,
    "UNDERAGE_WEIGHT": 60,
    "SANCTIONS_WEIGHT": 50,
    "PRIOR_REJECTION_WEIGHT": 10,
    "PRIOR_REJECTION_CAP": 3,
    "RISK_CEILING": 100,
    "APPROVAL_GATE": 70,  # score >= 70 blocks approval
    "SANCTIONED_LAST4": ["6666", "9999"],
}

# Overdraft / NSF tiered fee schedule (PRD §3.6)
FEE = {
    "TIER1_FEE_CENTS": 3000,        # ordinal 1
    "TIER2_4_FEE_CENTS": 3500,      # ordinals 2..4
    "DAILY_FEE_ITEM_CAP": 4,        # ordinal 5+ -> 0
}

# Inactivity thresholds (PRD §3.7)
DORMANCY = {
    "DORMANCY_THRESHOLD_DAYS": 365,
    "ESCHEAT_THRESHOLD_DAYS": 1095,
}

# Interest accrual (PRD §3.11)
INTEREST = {
    "DAY_COUNT_BASIS": 365,
    "BPS_DIVISOR": 10000,
}

# Account defaults (PRD §3.3, §3.5)
ACCOUNT_DEFAULTS = {
    "COURTESY_PAY_LIMIT_CENTS": 50000,
}
