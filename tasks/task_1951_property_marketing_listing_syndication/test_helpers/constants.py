"""Domain thresholds — numeric constants stated in the PRD."""

THRESHOLDS = {
    # PRD §3.5: rounding_increment_cents must be one of these values.
    "ALLOWED_ROUNDING_INCREMENTS_CENTS": (10000, 50000, 100000, 1000000),
    "DEFAULT_ROUNDING_INCREMENT_CENTS": 100000,
    # PRD §3.5: sla_seconds defaults to 3600 seconds when omitted.
    "DEFAULT_SLA_SECONDS": 3600,
    # PRD §3.5: fifteen minutes of blackout buffer added on each side at dispatch.
    "BLACKOUT_BUFFER_SECONDS": 900,
    # PRD §3.2: a PHOTO must be at least 1024 pixels wide and at least 768 pixels tall.
    "PHOTO_MIN_WIDTH_PX": 1024,
    "PHOTO_MIN_HEIGHT_PX": 768,
    # PRD §3.7: a price change needs |delta| >= 50000 cents or |delta_pct| >= 1.0.
    "PRICE_CHANGE_MIN_DELTA_CENTS": 50000,
    "PRICE_CHANGE_MIN_DELTA_PCT": 1.0,
    # PRD §3.8: feedback rating from 1 to 5 inclusive; half-life fourteen days.
    "RATING_MIN": 1,
    "RATING_MAX": 5,
    "FEEDBACK_HALF_LIFE_DAYS": 14,
    # PRD §3.9: relist fee constants and cooldown.
    "BASE_RELIST_FEE_CENTS": 20000,
    "VOLUME_THRESHOLD": 10,
    "DISCOUNT_THRESHOLD_PCT": 5.0,
    "RELIST_COOLDOWN_DAYS": 30,
    # PRD §3.6: third consecutive failure dead-letters the job.
    "JOB_MAX_ATTEMPTS": 3,
}

TEST_DEFAULTS = {
    "LIST_PRICE_CENTS": 50000000,
    "LISTING_EXPIRES_ON": "2027-01-01T00:00:00Z",
    "PHOTO_FILE_BYTES": 204800,
    "PHOTO_WIDTH_PX": 1600,
    "PHOTO_HEIGHT_PX": 1200,
    # PRD §2.4: the logical clock starts at exactly this instant.
    "CLOCK_DEFAULT_ISO": "2026-08-01T00:00:00Z",
}

# PRD §2.10: prohibited fair-housing phrases (case-insensitive substring match).
FAIR_HOUSING_PHRASES = (
    "no children",
    "adults only",
    "not suitable for families",
    "christian neighborhood",
    "no wheelchairs",
    "english speakers only",
)
