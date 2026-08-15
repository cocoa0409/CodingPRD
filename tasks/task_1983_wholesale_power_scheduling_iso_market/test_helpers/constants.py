"""Domain thresholds — numeric constants from PRD calculations."""

THRESHOLDS = {
    # collateral_requirement constants (PRD section 2.8)
    "REFERENCE_PRICE_CENTS_PER_MWH": 5000,
    "OFFER_RISK_FACTOR": 0.10,
    "CAPACITY_RISK_CENTS_PER_MW": 50000,
    "IG_UNSECURED_ALLOWANCE_CENTS": 100000,
    # imbalance_settlement constants (PRD section 3.5)
    "DEVIATION_DEADBAND_PCT": 0.05,
    "SHORT_PENALTY_MULT": 1.10,
    "LONG_CREDIT_MULT": 0.90,
    # ancillary_revenue constants (PRD section 3.6)
    "PERFORMANCE_FLOOR": 0.9,
    # capacity_performance_charge constants (PRD section 3.6)
    "PENALTY_RATE_CENTS_PER_MWH": 50000,
    # capacity_stop_loss_close constants (PRD section 3.6)
    "STOP_LOSS_FACTOR": 1.5,
    # credit_posture_evaluation constants (PRD section 2.8)
    "CURE_WINDOW_HOURS": 24,
}

TEST_DEFAULTS = {
    "CAPACITY_MW": 10,
    "OFFERED_MW": 10,
    "OFFER_PRICE": 5000,
    "OBLIGATED_MW": 10,
    "CAPACITY_RATE": 1000000,
}
