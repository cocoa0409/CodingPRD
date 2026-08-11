"""Domain thresholds — numeric constants stated in the PRD (§2, §3)."""

# Logical clock
DEFAULT_CLOCK_ISO = "2026-05-01T00:00:00Z"  # PRD §2.5

THRESHOLDS = {
    # Posture derivation (PRD §3.4)
    "MITE_WATCH_PER_100": 2.00,
    "MITE_TREATMENT_PER_100": 3.00,
    "MITE_QUARANTINE_PER_100": 9.00,
    "THRIVING_BROOD_MIN": 8,
    "WATCH_BROOD_BELOW": 6,
    "WATCH_STORES_BELOW_KG": 8,
    # Harvest net (PRD §3.5)
    "MOISTURE_LIMIT_PCT": 18.6,
    "MOISTURE_PENALTY_FACTOR": 2.0,
    # Honey share (PRD §3.6)
    "TIER_BONUS_BPS": {"BASIC": 0, "PLUS": 250, "PREMIUM": 500},
    "EDU_BONUS_BPS": 200,
    "SHARE_CAP_BPS": 6000,
    "RESERVE_POOL_TIER_KG": 100.000,
    "RESERVE_PCT_LOW": 0.03,
    "RESERVE_PCT_HIGH": 0.06,
    # Site capacity (PRD §2.8)
    "DEFAULT_BASE_CAPACITY_HIVES": 2,
    # Overwinter credit (PRD §3.9)
    "OVERWINTER_CREDIT_PER_HIVE_CENTS": 4000,
    # Billing (PRD §3.9)
    "MONTHLY_FEE_CENTS": {"BASIC": 2999, "PLUS": 4999, "PREMIUM": 7999},
    "LATE_FEE_PCT_PER_WEEK": 0.03,
    "DUE_DAYS": 7,
    # Removal (PRD §3.8)
    "COOLING_OFF_HOURS": 24,
    "CANCELLATION_FEE_CENTS": 7500,
    "REMOVAL_NOTICE_HOURS": 48,
    "CREW_BUFFER_HOURS": 2,
    # Swarm (PRD §3.7, §2.5)
    "SWARM_EXPIRY_HOURS": 72,
    # Waiver (PRD §3.1)
    "WAIVER_VALID_DAYS": 365,
    # Harvest freshness (PRD §3.5)
    "INSPECTION_FRESHNESS_DAYS": 30,
    # Treatment withdrawal (PRD §3.5)
    "WITHDRAWAL_DAYS": 14,
    # Reputation (PRD §3.1)
    "REPUTATION_START": 100,
    "REPUTATION_SEVERE_PENALTY": 15,
    "REPUTATION_MINOR_PENALTY": 5,
    "REPUTATION_AGREEMENT_GATE": 50,
    # Education (PRD §3.9)
    "QUIZ_PASS_SCORE": 80,
}

TEST_DEFAULTS = {
    "WAIVER_VERSION": "W-2026",
    "TERM_START": "2026-01-01T00:00:00Z",
    "TERM_END": "2026-12-31T00:00:00Z",
    "HOST_SHARE_BASE_BPS": 2500,
    "SEASON_NAME": "S2026",
    "SEASON_FROST": "2026-10-15T00:00:00Z",
    "NEXT_SEASON_NAME": "S2026-close",
    "NEXT_SEASON_FROST": "2027-10-15T00:00:00Z",
}

# Opaque operator ids used across scenarios (PRD §2.1: Beekeeper /
# ApiaryManager / PlatformOps ids are opaque and never entity-backed).
BEEKEEPER_1 = "bk-1"
BEEKEEPER_2 = "bk-2"
MANAGER_1 = "mgr-1"
