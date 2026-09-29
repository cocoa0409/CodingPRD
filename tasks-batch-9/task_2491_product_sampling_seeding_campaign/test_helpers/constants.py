"""Numeric and textual constants pinned by the PRD.

Every value here is stated literally in PRD.md; nothing is derived or guessed.
"""

# ---------------------------------------------------------------------------
# Logical clock (PRD §2.4)
# ---------------------------------------------------------------------------
CLOCK_EPOCH = "2026-08-01T00:00:00Z"

# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ---------------------------------------------------------------------------
# Campaign input defaults (PRD §3.1)
# ---------------------------------------------------------------------------
DEFAULT_REVIEW_DUE_DAYS = 21
DEFAULT_MIN_REVIEW_WORD_COUNT = 50
DEFAULT_HOLDOUT_PCT = 0.2

REVIEW_DUE_DAYS_MIN = 1
REVIEW_DUE_DAYS_MAX = 90
MIN_REVIEW_WORD_COUNT_MIN = 10
MIN_REVIEW_WORD_COUNT_MAX = 500
HOLDOUT_PCT_MIN = 0.0
HOLDOUT_PCT_MAX = 0.5
CAMPAIGN_NAME_MAX_LENGTH = 160
TARGET_SEGMENT_CODES_MIN = 1
TARGET_SEGMENT_CODES_MAX = 8
SYNDICATION_RETAILER_IDS_MAX = 8

# ---------------------------------------------------------------------------
# Panelist fraud risk scoring weights (PRD §3.3)
# ---------------------------------------------------------------------------
W_ADDR = 18
W_AGE = 22
W_STRIKE = 25
W_REFERRAL = 15
W_VELOCITY = 20
W_RESALE = 30
ACCOUNT_AGE_FLOOR_DAYS = 30
VELOCITY_TRIP_COUNT = 3
AUDIT_ADDR_MULTIPLIER = 1.5
FLAG_THRESHOLD_INCLUSIVE = 55.0

# ---------------------------------------------------------------------------
# Panelist cooldown (PRD §3.4)
# ---------------------------------------------------------------------------
PANELIST_COOLDOWN_DAYS = 14

# ---------------------------------------------------------------------------
# Compliance posture thresholds (PRD §2.9)
# ---------------------------------------------------------------------------
FROZEN_RATE = 0.2
FROZEN_ABS = 5
RESTRICTED_RATE = 0.05
RESTRICTED_DISCLOSURE_ABS = 3

# ---------------------------------------------------------------------------
# Review disclosure gate (PRD §3.7)
# ---------------------------------------------------------------------------
REQUIRED_DISCLOSURE_PHRASES = (
    "i received this product for free",
    "sample provided by",
)

# ---------------------------------------------------------------------------
# Syndication eligibility (PRD §3.8)
# ---------------------------------------------------------------------------
RATE_LIMIT_WINDOW_DAYS = 30
BADGE_PHRASE = "i received this product for free"

# ---------------------------------------------------------------------------
# Lift analysis and diversion penalty (PRD §3.9)
# ---------------------------------------------------------------------------
MATCH_CONFIDENCE_FLOOR = 0.8
CONVERSION_TAIL_DAYS = 30
MIN_TREATED_FOR_POWER = 3
PENALTY_TIER_LOW = 500
PENALTY_TIER_HIGH = 1500

# ---------------------------------------------------------------------------
# Canonical three-line kit used throughout the recipes.
# HERO-1  1417 x 1 @ 0.80 -> 283
# ACC-2    388 x 2 @ 0.85 -> 116
# INS-3    554 x 1 @ 0.90 ->  55
# kit_assembly_unit_cost_cents = 283 + 116 + 55 = 454, four units per kit.
# ---------------------------------------------------------------------------
CANONICAL_KIT_UNIT_COST_CENTS = 454
CANONICAL_KIT_UNIT_TOTAL = 4
CANONICAL_HERO_EXTENDED_CENTS = 283
CANONICAL_ACCESSORY_EXTENDED_CENTS = 116
CANONICAL_INSERT_EXTENDED_CENTS = 55

# Standard fulfillment-center freight used by the canonical fixtures, giving a
# committed cost of 454 + 300 = 754 cents per shipment.
CANONICAL_FREIGHT_CENTS_PER_KIT = 300
CANONICAL_COMMITTED_COST_CENTS = 754

# Standard campaign budget used by the canonical fixtures.
CANONICAL_BUDGET_TOTAL_CENTS = 1000000

# Sampling window used by the canonical fixtures.  It opens a month before the
# clock's startup instant so that a purchase recorded on the startup day always
# falls inside the window.
CANONICAL_WINDOW_START = "2026-07-01T00:00:00Z"
CANONICAL_WINDOW_END = "2026-09-30T00:00:00Z"

# Segment code shared by the canonical campaign and its panelists.
CANONICAL_SEGMENT_CODE = "URBAN_MILLENNIAL"

# Disclosure statement that satisfies the review disclosure gate.
VALID_DISCLOSURE_STATEMENT = "Sample provided by the brand for testing."

# Disclosure statement carrying the retailer badge phrase.
BADGE_DISCLOSURE_STATEMENT = "I received this product for free from the brand."
