"""Domain thresholds — numeric constants from PRD §3."""

THRESHOLDS = {
    # PRD §3.4: parts markup tiers keyed on unit_cost_cents
    "MARKUP_TIER1_MAX_CENTS": 100000,     # <= $1,000.00 -> 25%
    "MARKUP_TIER2_MAX_CENTS": 1000000,    # <= $10,000.00 -> 15%
    "MARKUP_TIER1_NUM": 125,              # 1.25 as basis-point-free integers
    "MARKUP_TIER1_DEN": 100,
    "MARKUP_TIER2_NUM": 115,
    "MARKUP_TIER2_DEN": 100,
    "MARKUP_TIER3_NUM": 110,
    "MARKUP_TIER3_DEN": 100,
    # PRD §3.7: exchange settlement constants
    "ADMIN_FEE_CENTS": 25000,             # flat $250.00
    "CORE_RETURN_DAYS": 15,
    "CORE_GRACE_DAYS": 5,
    "LATE_FEE_PER_DAY_CENTS": 50000,      # $500.00 per day
    "BER_CORE_CHARGE_PCT": 80,            # 80% of replacement value
    # PRD §3.1: default BER threshold percent
    "DEFAULT_BER_THRESHOLD_PCT": 65,
    # PRD §3.8: overage multiplier 1.5
    "OVERAGE_MULTIPLIER_NUM": 3,
    "OVERAGE_MULTIPLIER_DEN": 2,
}

TEST_DEFAULTS = {
    "CONTRACT_TAT_HOURS": 100,
    "TAT_PENALTY_RATE_CENTS_PER_HOUR": 5000,
    "TAT_PENALTY_CAP_PCT": 50,
    "CREDIT_LIMIT_CENTS": 1000000000,
    "REPLACEMENT_VALUE_CENTS": 10000000,
    "WARRANTY_CYCLE_LIMIT": 500,
    "WARRANTY_MONTH_LIMIT": 24,
    "FLAT_OVERHAUL_PRICE_CENTS": 2000000,
    "LABOR_ESTIMATE_CENTS": 2000000,
    "PARTS_ESTIMATE_CENTS": 1000000,
    "HOURLY_RATE_CENTS": 100000,
    "DAILY_RATE_CENTS": 100000,
    "PART_NUMBER": "PN-32-ACT",
    "ATA_CHAPTER": "32",
    "CMM_REFERENCE": "CMM-32-11-01",
    # Logical clock default (PRD §2.5)
    "CLOCK_DEFAULT_ISO": "2026-08-01T00:00:00Z",
    # Opaque user identifiers used by Inspector/Technician flows (PRD §2.1)
    "TECH_USER_ID": "tech-1",
    "INSPECTOR_USER_ID": "insp-9",
}
