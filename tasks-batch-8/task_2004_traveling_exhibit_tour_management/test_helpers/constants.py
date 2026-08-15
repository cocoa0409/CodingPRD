"""Domain thresholds — numeric constants from PRD §3 calculations."""

THRESHOLDS = {
    # Participation fee tiers (PRD §3.3)
    "TIER1_MAX_ATTENDANCE": 10_000,
    "TIER2_MAX_ATTENDANCE": 50_000,
    "TIER2_UPLIFT_PCT": 0.10,
    "TIER3_UPLIFT_PCT": 0.25,
    "CANCEL_PENALTY_PCT": 0.30,
    # Condition score (PRD §3.7)
    "W_SURFACE": 0.4,
    "W_STRUCTURAL": 0.6,
    "SEAL_BREACH_CAP": 40,
    "DAMAGE_THRESHOLD": 70,
    # Damage claim payout (PRD §3.7)
    "LINE_COVERAGE_PCT": 0.80,
    "CLAIM_CAP_PCT": 0.90,
    # Marketing kit cost (PRD §3.4)
    "KIT_BASE_CENTS": 150_000,
    "KIT_PER_LANG_CENTS": 45_000,
    "KIT_BULK_LANG_MIN": 3,
    "KIT_BULK_DISCOUNT_PCT": 0.15,
    "KIT_PER_LOGO_CENTS": 20_000,
}

TEST_DEFAULTS = {
    "DECLARED_VALUE_CENTS": 1_000_000,
    "BASE_FEE_CENTS": 100_000,
    "PROJECTED_ATTENDANCE": 1000,
    "CLOCK_START": "2026-08-01T00:00:00Z",
}
