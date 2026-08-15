"""Domain thresholds — numeric constants stated in the PRD (§2.5, §3.3–§3.7)."""

THRESHOLDS = {
    # Statutory lien cap (PRD §3.3): "the statutory lien cap of 250,000 cents"
    "STATUTORY_LIEN_CAP_CENTS": 250000,
    # Recovery formula constants (PRD §3.4)
    "DEFAULT_MEDICAL_RATIO": 0.35,
    "COST_SHARE_CAP_PCT": 0.25,
    # Contractor commission tiers (PRD §3.5)
    "COMM_TIER1_CAP_CENTS": 100000,
    "COMM_TIER1_RATE": 0.10,
    "COMM_TIER2_WIDTH_CENTS": 100000,
    "COMM_TIER2_RATE": 0.075,
    "COMM_TIER3_RATE": 0.05,
    # Hardship gates and deadlines (PRD §3.6, §3.7)
    "HOMESTEAD_EXEMPT_CAP_CENTS": 5000000,
    "INCOME_LIMIT_CENTS": 3000000,
    "ESTATE_FILING_DAYS": 365,
    "NOTICE_DEADLINE_DAYS": 30,
    "SOL_YEARS": 3,
    "EPISODE_WINDOW_DAYS": 90,
    "NEGOTIATION_FREEZE_DAYS": 14,
    "MAX_APPEALS": 1,
}

TEST_DEFAULTS = {
    # The logical clock before any clock call (PRD §2.5).
    "DEFAULT_CLOCK_ISO": "2026-08-01T00:00:00Z",
    "DEFAULT_CLOCK_DATE": "2026-08-01",
    "DEFAULT_INJURY_DATE": "2026-01-01",
    "DEFAULT_SERVICE_DATE": "2026-01-10",
}
