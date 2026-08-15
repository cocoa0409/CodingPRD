"""Domain thresholds and numeric constants from the PRD (§2-§3)."""

# Logical clock default (PRD §2.5): before any request, the clock reads this.
CLOCK_EPOCH = "2026-08-01T00:00:00Z"

THRESHOLDS = {
    # Refund calculation (PRD §3.9)
    "COOLING_OFF_DAYS": 14,
    "PER_SESSION_COOLING_OFF_CENTS": 7500,
    "ADMIN_FEE_CENTS": 5000,
    # Engagement score (PRD §3.6)
    "ENGAGEMENT_WINDOW_DAYS": 28,
    "ENGAGEMENT_SESSIONS_EXPECTED_28": 8,
    # Reschedule policy (PRD §3.4)
    "RESCHEDULE_FREE_HOURS": 24,
    # Session overlap buffer (PRD §2.9)
    "BUFFER_MINUTES": 15,
    # Installment cadence (PRD §3.3)
    "INSTALLMENT_INTERVAL_DAYS": 30,
    # Pause limit (PRD §3.5)
    "PAUSE_LIMIT": 2,
    # Delinquency fuse (PRD §3.3)
    "GRACE_DAYS": 14,
    # Field ranges (PRD §2.11)
    "SESSION_DURATION_MIN": 30,
    "SESSION_DURATION_MAX": 120,
    "DISCOVERY_DURATION_MIN": 15,
    "OUTCOME_RATING_MIN": 1,
    "OUTCOME_RATING_MAX": 5,
    "COHORT_CAPACITY_MIN": 2,
}

# Standard program tier used across most fixtures.
TIER_PKG8 = {
    "tier_code": "PKG-8",
    "tier_type": "PACKAGE",
    "session_count": 8,
    "price_cents": 80000,
    "duration_days": 56,
    "installment_count_allowed": 3,
    "reschedule_cap": 2,
}

# Single-session tier: completing its one session bubbles the enrollment up.
TIER_SINGLE1 = {
    "tier_code": "SINGLE-1",
    "tier_type": "SINGLE",
    "session_count": 1,
    "price_cents": 15000,
    "duration_days": 30,
    "installment_count_allowed": 1,
    "reschedule_cap": 0,
}

# Membership tier used by the pro-rata tiered-branch scenarios.
TIER_MEM12 = {
    "tier_code": "MEM-12",
    "tier_type": "MEMBERSHIP",
    "session_count": 12,
    "price_cents": 120000,
    "duration_days": 84,
    "installment_count_allowed": 1,
    "reschedule_cap": 1,
}

# Package tier with reschedule_cap 1 (cap-exhaustion scenarios).
TIER_PKG_CAP1 = {
    "tier_code": "PKG-CAP1",
    "tier_type": "PACKAGE",
    "session_count": 8,
    "price_cents": 80000,
    "duration_days": 56,
    "installment_count_allowed": 3,
    "reschedule_cap": 1,
}

TEST_DEFAULTS = {
    "COACH_EXPIRES_FAR": "2027-01-01",
    "DISCOVERY_DURATION": 45,
    "SESSION_DURATION": 60,
    "TIMEZONE": "UTC",
}
