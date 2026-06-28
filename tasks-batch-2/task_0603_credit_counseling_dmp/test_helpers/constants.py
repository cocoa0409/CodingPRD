"""Domain thresholds — numeric constants from PRD calculations."""

THRESHOLDS = {
    "MIN_ENROLL_DTI": 15.0,          # back_end_dti must be >= this percentage to enroll
    "MISSED_DEPOSIT_LIMIT": 3,       # streak at or above this triggers DEFAULTED
    "SETUP_FEE_CAP_CENTS": 5000,     # regulatory cap on Agency.setup_fee_cents
    "MONTHLY_FEE_CAP_CENTS": 7500,   # regulatory cap on Agency.monthly_fee_cents
    "LATE_FEE_THRESHOLD_APR": 0.10,  # accounts whose original_apr > this are high_interest
}

TEST_DEFAULTS = {
    "SETUP_FEE_CENTS": 5000,
    "MONTHLY_FEE_CENTS": 3500,
    "DEFAULT_CONCESSION_APR": 0.0699,
    "MIN_PROPOSED_PAYMENT_PCT": 0.02,
}
