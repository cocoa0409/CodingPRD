"""Domain thresholds — numeric constants from the PRD's calculation rules (§3)."""

THRESHOLDS = {
    # Dealer tier thresholds on ytd_purchase_cents (PRD §3.1)
    "SILVER_THRESHOLD_CENTS": 5_000_000,
    "GOLD_THRESHOLD_CENTS": 20_000_000,
    "PLATINUM_THRESHOLD_CENTS": 50_000_000,
    # AHRI classification thresholds (PRD §3.2)
    "PREMIUM_SEER2": 17.0,
    "PREMIUM_EER2": 12.0,
    "HIGH_SEER2": 15.2,
    "HIGH_EER2": 11.7,
    "HEATPUMP_HSPF2_MIN": 8.1,
    # Refrigerant compliance (PRD §3.7)
    "HEEL_MIN_FRACTION": 0.90,
    "CYLINDER_OVERDUE_DAYS": 30,
    # Warranty (PRD §3.6)
    "REGISTRATION_WINDOW_DAYS": 60,
    "EXTENDED_COVERAGE_YEARS_ON_TIME": 10,
    "BASE_COVERAGE_YEARS": 5,
    "MAX_REVISION_CYCLES": 3,
    # Rebates (PRD §3.8)
    "REBATE_DECISION_DAYS": 45,
    "PREMIUM_REBATE_CENTS": 200_000,
    "HIGH_REBATE_CENTS": 100_000,
    "FEDERAL_COST_CAP_PCT": 0.30,
    # Training credits (PRD §3.9)
    "CREDIT_TTL_MONTHS": 24,
}

TIER_DISCOUNT_PCT = {
    "STANDARD": 0.00,
    "SILVER": 0.03,
    "GOLD": 0.05,
    "PLATINUM": 0.07,
}

COOP_ACCRUAL_RATE = 0.02

TEST_DEFAULTS = {
    "LIST_PRICE_CENTS": 500_000,
    "TARE_WEIGHT_LBS": 20.00,
    "FULL_WEIGHT_LBS": 50.00,
    "DEFAULT_CLOCK": "2026-08-01T00:00:00Z",
}

ALL_DOC_KINDS = ["AHRI_CERTIFICATE", "INVOICE", "LOAD_CALC", "PERMIT"]
