"""Domain thresholds — numeric constants from the PRD's calculation rules."""

# Logical clock startup default (PRD section 2.5).
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

# Hold lifetime (PRD section 3.5): held_until = created_at + 72h.
HOLD_HOURS = 72

# Permit renewal window (PRD section 3.2): RENEWAL_PENDING from 30 days
# before expires_on up to (not including) expires_on.
PERMIT_RENEWAL_WINDOW_DAYS = 30

# Missed-posting grace (PRD section 3.7): BOOKED/ART_CLEARED -> MISSED when
# the clock reaches three days after start_date with no verified posting.
MISSED_GRACE_DAYS = 3

# On-time posting bound (PRD section 3.6): posted_on <= start_date + 2 days
# is on time; later is a late (MISSED -> LIVE) posting.
LATE_POSTING_GRACE_DAYS = 2

# Posting date window (PRD section 3.6): posted_on no earlier than seven days
# before start_date and no later than the clock's current date.
POSTING_LOOKBACK_DAYS = 7

# Holdover premium (PRD section 3.7): holdover weeks bill at 1.10x the
# pinned weekly rate.
HOLDOVER_RATE_PCT = 1.10

# Impressions (PRD section 3.8): illumination factor for lit faces.
ILLUMINATION_FACTOR = 1.12

# Volume discount tiers (PRD section 3.5).
TIER_1_FLOOR_CENTS = 5_000_000
TIER_1_PCT = 0.05
TIER_2_FLOOR_CENTS = 15_000_000
TIER_2_PCT = 0.10

# Artwork revision surcharge (PRD section 3.6): first two revisions free,
# 35000 cents per revision beyond.
FREE_REVISIONS = 2
REVISION_CHARGE_CENTS = 35_000

# Cancellation fee tiers in whole days before start (PRD section 3.5).
CANCEL_TIER_10PCT_MIN_DAYS = 28
CANCEL_TIER_25PCT_MIN_DAYS = 14
CANCEL_FEE_10_PCT = 0.10
CANCEL_FEE_25_PCT = 0.25
CANCEL_FEE_50_PCT = 0.50

# Make-good constants (PRD section 3.9).
ILLUMINATION_CREDIT_PCT = 0.15
AUDIENCE_GUARANTEE_RATIO = 0.90

# Static-face changeover (PRD section 3.5): one full free day between
# campaigns on a STATIC face.
STATIC_CHANGEOVER_GAP_DAYS = 1

# Standard rate-card knobs used across scenarios.
RATE_CARD_STATIC = {
    "market_code": "NYC",
    "display_type": "STATIC",
    "base_weekly_cents": 200_000,
    "illumination_premium_pct": 0.15,
    "traffic_tier_1_threshold": 100_000,
    "traffic_tier_1_uplift_pct": 0.10,
    "traffic_tier_2_threshold": 250_000,
    "traffic_tier_2_uplift_pct": 0.25,
}

TEST_DEFAULTS = {
    "ADVERTISER_NAME": "Acme",
    "CREDIT_LIMIT_CENTS": 90_000_000,
    "CAMPAIGN_START": "2026-08-01",
    "CAMPAIGN_END": "2026-09-30",
    "FLIGHT_START": "2026-08-10",
    "FLIGHT_END": "2026-09-06",
    "PERMIT_ISSUED": "2026-07-01T00:00:00Z",
    "PERMIT_EXPIRES": "2026-12-31T00:00:00Z",
    "FACE_WIDTH": 168,
    "FACE_HEIGHT": 576,
    "JURISDICTION": "NYC DOB",
}
