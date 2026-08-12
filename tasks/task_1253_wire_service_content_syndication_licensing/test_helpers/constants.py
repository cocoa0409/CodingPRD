"""Domain thresholds — numeric constants from the PRD's calculation rules."""

# Logical clock: server starts at 2026-05-01T00:00:00Z before any clock call.
CLOCK_INITIAL = "2026-05-01T00:00:00Z"
# Common working instant used by most scenarios.
DEFAULT_WORK_CLOCK = "2026-05-10T00:00:00Z"

THRESHOLDS = {
    # Pricing
    "BASIS_POINTS_DENOMINATOR": 10_000,  # 10000 bp == 1.0x multiplier
    # Subscription cancellation minimum commitment (months)
    "MIN_COMMITMENT_MONTHS": 3,
    # Subscriber termination notice period (days)
    "TERMINATION_NOTICE_DAYS": 30,
    # Renewal notice must be dispatched at least this many days before renewal_due_at
    "RENEWAL_NOTICE_MIN_DAYS": 60,
    # Member contribution credit: word-count brackets (in cents)
    "WORD_BRACKET_SHORT_MAX": 400,     # body_word_count < 400 -> 2000
    "WORD_BRACKET_MEDIUM_MAX": 900,    # < 900 -> 5000
    "WORD_BRACKET_LONG_MAX": 1500,     # < 1500 -> 9000; >= 1500 -> 14000
    "WORD_BRACKET_SHORT_CENTS": 2_000,
    "WORD_BRACKET_MEDIUM_CENTS": 5_000,
    "WORD_BRACKET_LONG_CENTS": 9_000,
    "WORD_BRACKET_FEATURE_CENTS": 14_000,
    # Member contribution credit: per-asset bonuses (in cents)
    "PHOTO_BONUS_CENTS": 1_500,
    "VIDEO_BONUS_CENTS": 4_000,
}

TEST_DEFAULTS = {
    "PACKAGE_BASE_FEE_CENTS": 10_000,
    "TIER_MULTIPLIER_BP": 10_000,
    "TIER_QUOTA": 5,
    "TIER_OVERAGE_CENTS": 100,
    "SUBSCRIBER_AUDIENCE": 5_000,
}
