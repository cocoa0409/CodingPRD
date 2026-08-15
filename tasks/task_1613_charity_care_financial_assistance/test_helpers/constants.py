"""Domain thresholds — numeric constants from PRD calculations (§2.4, §3)."""

# Logical clock startup default (PRD §2.4).
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"

# Annualization factors for verified income documents (PRD §3.6).
ANNUALIZATION = {"PAY_STUB": 26, "BENEFIT_LETTER": 12, "TAX_RETURN": 1}

# Presumptive scoring factor weights (PRD §3.7); full file sums to exactly 1.00.
SCREENING_WEIGHTS = {
    "income_band": 0.35,
    "payment_history": 0.25,
    "utilization": 0.15,
    "public_benefit": 0.15,
    "housing_stability": 0.10,
}

# Flat presumptive-path discount percentages (PRD §3.8).
PRESUMPTIVE_FULL_DISCOUNT_PCT = 100.00
PRESUMPTIVE_PARTIAL_DISCOUNT_PCT = 50.00

# Standard 501(r) policy configuration used by most scenarios (PRD §3.1).
STANDARD_POLICY_PARAMS = {
    "policy_code": "FAP-2026",
    "fpl_base_cents": 1500000,
    "fpl_increment_cents": 500000,
    "full_discount_max_fpl_pct": 200,
    "partial_discount_max_fpl_pct": 300,
    "partial_discount_floor_pct": 50.0,
    "asset_limit_cents": 2500000,
    "retroactive_window_days": 240,
    "notification_period_days": 120,
    "eca_notice_days": 30,
    "doc_response_days": 30,
    "presumptive_partial_score_threshold": 70.0,
    "presumptive_full_score_threshold": 90.0,
    "effective_from": "2026-01-01T00:00:00Z",
    "effective_to": "2027-01-01T00:00:00Z",
}
