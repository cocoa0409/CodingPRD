"""Domain thresholds — numeric constants from the PRD."""

DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

POLICY_DEFAULTS = {
    "min_tenure_days": 90,
    "duplicate_cooldown_months": 6,
    "referral_expiry_days": 45,
    "hire_pct": 30,
    "retention_days": 180,
    "clawback_days": 90,
    "annual_cap_cents": 2_000_000,
    "velocity_limit": 5,
    "tier_ic_cents": 150_000,
    "tier_senior_cents": 300_000,
    "tier_manager_cents": 500_000,
    "tier_director_cents": 650_000,
    "tier_executive_cents": 800_000,
}

THRESHOLDS = {
    "SUSPEND_RISK_SCORE": 100,
    "RISK_SCORE_CAP": 500,
    "RISK_HALFLIFE_DAYS": 180,
    "VELOCITY_WINDOW_DAYS": 7,
    "RING_WINDOW_DAYS": 90,
    "RING_MIN_REFERRERS": 3,
    "FLAT_RATE_BPS": 2200,
    "BRACKET_1_LIMIT": 500_000,
    "BRACKET_2_LIMIT": 1_500_000,
    "LOW_CONFIDENCE_MIN": 10,
    "SMOOTHING_K": 5,
}

RISK_WEIGHTS = {
    "SELF_REFERRAL": 40,
    "VELOCITY": 25,
    "DUPLICATE_RING": 35,
    "RESUME_FARM": 50,
    "MANUAL": 20,
}

TEST_DEFAULTS = {
    "DEPARTMENT": "ENGINEERING",
    "TALENT_DEPARTMENT": "TALENT",
    "HIRE_DATE": "2026-01-01T00:00:00Z",
    "POLICY_EFFECTIVE_FROM": "2026-01-01T00:00:00Z",
    "DEFAULT_HIRE_DATE_ACTION": "2026-08-01T00:00:00Z",
    "RETENTION_DUE_DEFAULT": "2027-01-28T00:00:00Z",
    "CLAWBACK_UNTIL_DEFAULT": "2027-04-28T00:00:00Z",
}
