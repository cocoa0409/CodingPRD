"""Domain thresholds — numeric constants from PRD calculations (§2.6, §3.2, §3.3, §3.5)."""

# underwriting_risk_score (PRD §3.2)
RISK_SCORE = {
    "W_INCOME": 0.4,
    "W_CREDIT": 0.4,
    "W_EVICTION": 0.2,
    "TARGET_INCOME_RATIO": 3.0,
    "AUTO_APPROVE_THRESHOLD": 35,
    "LOW_TIER_MAX": 20,
    "MEDIUM_TIER_MAX": 50,
}

# monthly_fee_calculation (PRD §3.3)
MONTHLY_FEE = {
    "BASE_RATE_PCT": 0.008,
    "FLAT_ADMIN_FEE_CENTS": 150,
    "MIN_FEE_CENTS": 1500,
    "RISK_MULTIPLIER": {"LOW": 1.0, "MEDIUM": 1.3, "HIGH": 1.6},
}

# premium_installment_allocation (PRD §3.3)
PREMIUM_ALLOCATION = {
    "INSURANCE_PREMIUM_PCT": 0.85,
    "PLATFORM_FEE_PCT": 0.10,
    "STATE_TAX_PCT": 0.05,
}

# claim_payout_calculation (PRD §3.5)
CLAIM_PAYOUT = {
    "FLAT_DEDUCTIBLE_CENTS": 5000,
    "HIGH_TIER_THRESHOLD_CENTS": 200000,
    "HIGH_TIER_DEDUCTIBLE_MULTIPLIER": 1.5,
}

# billing cycle (PRD §3.3)
OVERDUE_GRACE_DAYS = 5
INVOICE_DUE_DAYS = 10

TEST_DEFAULTS = {
    "MONTHLY_RENT_CENTS": 200000,
    "COVERAGE_LIMIT_CENTS": 300000,
}
