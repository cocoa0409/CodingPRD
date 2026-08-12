"""Domain thresholds — numeric constants from the PRD's calculation rules (§2.6, §3)."""

# Boot value of the server logical clock (PRD §2.5).
BOOT_CLOCK_ISO = "2026-05-01T00:00:00Z"

THRESHOLDS = {
    # Minimum premium floor, applied after rounding (PRD §2.6).
    "MIN_PREMIUM_CENTS": 25000,
    # Cast premium loadings (PRD §3.1).
    "STUNT_LOADING_PER_STUNT": 0.10,
    "STUNT_LOADING_CAP": 1.50,
    "ESSENTIAL_ELEMENT_LOADING": 1.20,
    "FOREIGN_TRAVEL_LOADING_PER_TRAVELER": 0.05,
    "FOREIGN_TRAVEL_LOADING_CAP": 1.40,
    # Aggregate deductible cap = one quarter of aggregate_limit_cents (PRD §3.8).
    "AGGREGATE_DEDUCTIBLE_CAP_FRACTION": 0.25,
    # Bond premium tiers on bond_amount_cents (PRD §3.7).
    "BOND_TIER1_UPPER_CENTS": 100000000,
    "BOND_TIER1_RATE": 0.0200,
    "BOND_TIER2_UPPER_CENTS": 500000000,
    "BOND_TIER2_RATE": 0.0150,
    "BOND_TIER3_UPPER_CENTS": 2500000000,
    "BOND_TIER3_RATE": 0.0110,
    "BOND_TIER4_RATE": 0.0085,
    # Bond amount must cover at least half of budget (PRD §3.7).
    "BOND_COVER_MIN_PCT": 50,
    # Certificate outer envelope extension past principal photography (PRD §3.5).
    "POST_PRODUCTION_EXTENSION_DAYS": 30,
    # Foreign travel envelope buffer on each side of photography (PRD §3.6).
    "FOREIGN_TRAVEL_BUFFER_DAYS": 14,
    # Renewal offer lifetime (PRD §3.10).
    "RENEWAL_OFFER_DAYS": 14,
    # Renewal loading tiers on loss_ratio_pct (PRD §3.10).
    "RATIO_T1_MAX": 3000,
    "RATIO_T1_FACTOR": 0.90,
    "RATIO_T2_MAX": 6000,
    "RATIO_T2_FACTOR": 1.00,
    "RATIO_T3_MAX": 9000,
    "RATIO_T3_FACTOR": 1.15,
    "RATIO_T4_FACTOR": 1.40,
}

# Base premium rates per coverage line (PRD §3.1).
BASE_RATE_PCT = {
    "GENERAL_LIABILITY": 0.0120,
    "EQUIPMENT": 0.0185,
    "CAST": 0.0275,
    "ERRORS_OMISSIONS": 0.0350,
    "FOREIGN_TRAVEL": 0.0420,
}

# Risk multiplier per production_type (PRD §3.1).
RISK_MULTIPLIER = {
    "FEATURE": 1.00,
    "EPISODIC": 1.15,
    "DOCUMENTARY": 0.85,
    "COMMERCIAL": 0.90,
    "MUSIC_VIDEO": 1.05,
}

TEST_DEFAULTS = {
    "BUDGET_CENTS": 100000000,
    "POLICY_LIMIT_CENTS": 100000000,
    "POLICY_AGGREGATE_LIMIT_CENTS": 200000000,
    "POLICY_DEDUCTIBLE_CENTS": 100000,
    "PAYROLL_BASIS_CENTS": 10000000,
}
