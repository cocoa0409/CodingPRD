"""Domain thresholds and money constants from PRD §2.6-§2.9, §3.2-§3.9."""

# Logical clock startup default (PRD §2.7).
CLOCK_START_ISO = "2026-08-01T00:00:00Z"

THRESHOLDS = {
    # Coverage requirement (PRD §3.2)
    "EM_SHARE_CAP": 0.40,
    # Selection sizing / scoring (PRD §3.3)
    "NOTICE_ALLOCATION_DAYS": 30,
    "W_RECENCY": 50,
    "COMPLIANCE_BASE": 30,
    "COMPLIANCE_STEP": 10,
    "PENALTY_WEIGHT": 5,
    "GEAR_PRIORITY_MULTIPLIER": 1.25,
    "RECENCY_NULL_DAYS": 365,
    "RECENCY_CAP_DAYS": 365,
    # Sea-day accounting / deployment length (PRD §2.9, §3.4)
    "MAX_DEPLOYMENT_SEA_DAYS": 45,
    # Observer capacity (PRD §3.4)
    "OBSERVER_MAX_COMMITTED_SEA_DAYS": 90,
    "TRAINEE_MAX_CONSECUTIVE": 20,
    "CERTIFIED_MAX_CONSECUTIVE": 30,
    "LEAD_MAX_CONSECUTIVE": 45,
    # Cost recovery (PRD §3.9)
    "RATE_TIER1_CENTS": 39900,
    "RATE_TIER2_CENTS": 49900,
    "TIER1_LIMIT_DAYS": 20,
    "SURCHARGE_PCT": 0.037,
    "SMALL_VESSEL_LENGTH_FT": 40,
    "SMALL_VESSEL_RATE_FACTOR": 0.5,
    "FEE_CAP_PCT": 0.005,
    "INVOICE_DUE_DAYS": 30,
    # EM review (PRD §3.8)
    "EM_REVIEW_MIN_PCT": 0.30,
    # Sampling (PRD §3.5, §3.6)
    "MIN_SAMPLE_RATIO": 0.20,
    "MIN_VERIFIED_COVERAGE": 0.20,
}

TEST_DEFAULTS = {
    "REGION": "Bering Sea",
    "HOME_PORT": "Kodiak",
    "COVERAGE_TARGET_PCT": 0.30,
    "PRIORITY_GEAR": "TRAWL",
    "PLAN_PERIOD_START": "2026-09-01T00:00:00Z",
    "PLAN_PERIOD_END": "2026-12-31T00:00:00Z",
    "NOTICE_RESPONSE_DEADLINE": "2026-09-05T00:00:00Z",
    "DEPARTURE": "2026-09-10T00:00:00Z",
    "RETURN": "2026-09-19T00:00:00Z",
    "HAUL_DATE": "2026-09-12T00:00:00Z",
}
