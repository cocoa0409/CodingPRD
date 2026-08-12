"""Domain thresholds and default test data (PRD sections 2 and 3)."""

# Numeric thresholds named in the PRD.
THRESHOLDS = {
    # Four-fifths screening threshold for the denial impact ratio.
    "FOUR_FIFTHS_THRESHOLD": 0.80,
    # Net-ratio classification floor for NONE.
    "NONE_FLOOR": 0.90,
    # Strictly-greater pricing spread that auto-flags a pricing finding.
    "PRICING_FLAG_THRESHOLD_BPS": 15,
    # Conditional-authority pool threshold for CAP approvals.
    "DIRECTOR_POOL_THRESHOLD_CENTS": 25_000_000,
    # Officer risk-score norms and weights.
    "OVERRIDE_NORM": 0.20,
    "EXCEPTION_NORM": 0.10,
    "DISPERSION_NORM_BPS": 70,
    "WEIGHT_OVERRIDE": 40,
    "WEIGHT_EXCEPTION": 35,
    "WEIGHT_DISPERSION": 25,
    "WATCH_FLOOR": 40.0,
    "RED_FLOOR": 70.0,
    # Monitoring-cycle timing rules.
    "EXCEPTION_EXPIRY_DAYS": 30,
    "PRIVILEGE_FORFEIT_CYCLES": 2,
    # Selector comparability bound on credit-score difference.
    "MATCHED_PAIR_MAX_CREDIT_DIFF": 40,
}

# Logical-clock startup default named in the PRD.
CLOCK_DEFAULT_ISO = "2026-05-01T00:00:00Z"

# Shared market fixture values used across suites.
MARKET_DEFAULT = {
    "name": "Metro One",
    "msa_code": "M001",
    "protected_group_population_share": 0.40,
    "peer_group_code": "PG7",
}
BRANCH_DEFAULT = {
    "name": "Main",
    "tract_minority_pct": 55.0,
    "opened_on": "2020-01-15",
}
OFFICER_DEFAULT = {"full_name": "Officer One"}

# Canonical analysis window (2026 Q1) and standard application defaults.
Q1_2026_START = "2026-01-01"
Q1_2026_END = "2026-04-01"

APPLICATION_DEFAULT = {
    "product_type": "CONVENTIONAL",
    "applicant_group": "CONTROL",
    "outcome": "ORIGINATED",
    "note_rate_bps": 700,
    "loan_amount_cents": 30_000_000,
    "credit_score": 720,
    "dti_pct": 36.0,
    "application_date": "2026-01-05",
    "decision_date": "2026-01-20",
}
