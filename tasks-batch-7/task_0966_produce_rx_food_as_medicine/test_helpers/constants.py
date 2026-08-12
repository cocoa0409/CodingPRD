"""Domain thresholds and canonical defaults from the PRD (§2.6, §3.4, §3.6, §3.9)."""

THRESHOLDS = {
    # Referral expiry: strictly greater than fourteen days expires (PRD §3.9).
    "REFERRAL_EXPIRY_DAYS": 14,
    # Education venue turnover buffer in minutes (PRD §3.6).
    "VENUE_BUFFER_MINUTES": 30,
    # A1c clinical plausibility range, inclusive (PRD §3.7).
    "A1C_MIN": 3.0,
    "A1C_MAX": 20.0,
    # Engagement-tier benefit multipliers (PRD §3.4).
    "TIER_T1_MULT": 1.00,
    "TIER_T2_MULT": 1.10,
    "TIER_T3_MULT": 1.25,
    # Urgent-referral benefit multiplier (PRD §3.4).
    "URGENT_MULT": 1.10,
}

# Canonical program economics used across the suite (PRD §3.1).
CANONICAL_PROGRAM = {
    "BASE_MONTHLY_BENEFIT_CENTS": 10000,
    "HOUSEHOLD_INCREMENT_CENTS": 2500,
    "MAX_HOUSEHOLD_SIZE": 6,
    "DOUBLE_UP_MULTIPLIER": 1.0,
    "DOUBLE_UP_DAILY_CAP_CENTS": 100000,
    "DOUBLE_UP_POOL_CENTS": 200000,
    "TIER2_COMPLETIONS": 3,
    "TIER3_COMPLETIONS": 6,
    "RENEWAL_WINDOW_DAYS": 30,
    "OUTCOME_IMPROVEMENT_THRESHOLD": 0.5,
    "START_DATE": "2026-05-01",
    "END_DATE": "2026-10-31",
}

TEST_DEFAULTS = {
    "FUNDER_COMMITMENT_CENTS": 1000000,
    "POOL_COMMITTED_CENTS": 500000,
    # Face value for household_size 2 at T1 / STANDARD: 10000 + 2500.
    "FACE_HH2_CENTS": 12500,
    # Face value for household_size 1 at T1 / STANDARD: base only.
    "FACE_HH1_CENTS": 10000,
}

# Logical clock epoch (PRD §2.5): before any call it reads exactly this instant.
LOGICAL_CLOCK_EPOCH = "2026-05-01T00:00:00Z"
