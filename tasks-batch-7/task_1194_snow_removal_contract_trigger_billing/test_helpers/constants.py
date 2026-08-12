"""Domain thresholds — numeric constants named in the PRD."""

# Fixed startup logical clock (PRD §2.4).
DEFAULT_CLOCK = "2026-05-01T00:00:00.000Z"

THRESHOLDS = {
    "VERIFICATION_SOURCE_QUORUM": 2,
    "VERIFICATION_OBSERVATION_GRACE_HOURS": 6,
    "CHALLENGE_WINDOW_HOURS": 48,
    "PHOTO_ACCEPT_WINDOW_MINUTES": 360,
    "BACKUP_GRACE_MINUTES": 120,
    "REAPPLY_GAP_MINUTES": 90,
    "POST_SEASON_BILLING_DAYS": 60,
    "RELIABILITY_SUSPEND_FLOOR": 70,
    "RELIABILITY_MIN_ASSIGNMENTS": 3,
    "DOCUMENTATION_MIN_SCORE": 60,
    "BILLING_INCREMENT_MINUTES": 6,
}

# Contract creation defaults (PRD §3.1).
CONTRACT_DEFAULTS = {
    "trigger_depth_inches": 2.0,
    "hourly_tier_threshold_minutes": 2400,
    "night_premium_pct": 0.25,
    "sla_miss_penalty_cents": 15000,
    "require_photo_verification": True,
    "salt_rate_per_lb_cents": 25,
    "blend_rate_per_lb_cents": 60,
    "brine_rate_per_lb_cents": 35,
}

# Area-normative material rates in lbs per sqft (PRD §3.9).
NORMATIVE_RATE = {
    "ROCK_SALT": 0.0023,
    "ICE_MELT_BLEND": 0.0015,
    "LIQUID_BRINE": 0.0040,
}

# Documentation completeness weights (PRD §3.8); each set sums to 100.
W_STANDARD = {"before": 15, "after": 25, "material": 20, "timeliness": 20, "weather": 20}
W_STRICT = {"before": 30, "after": 40, "material": 10, "timeliness": 10, "weather": 10}

# Standard season window used across fixtures.
SEASON_START = "2026-11-01T00:00:00Z"
SEASON_END = "2027-03-31T23:59:59Z"
SHORT_SEASON_END = "2026-12-31T23:59:59Z"
