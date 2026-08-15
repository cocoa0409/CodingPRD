"""Domain thresholds — numeric constants from PRD Section 3 calculations."""

# Space pricing ladder (PRD Section 3.3)
TIER_2_SOLD_AT = 20          # sold_count >= 20 moves pricing to tier two
TIER_3_SOLD_AT = 45          # sold_count >= 45 moves pricing to tier three
TIER_1_MULT = 1.00
TIER_2_MULT = 1.20
TIER_3_MULT = 1.45
DISCOUNT_5PCT_SUBTOTAL_CENTS = 150000
DISCOUNT_10PCT_SUBTOTAL_CENTS = 300000
DISCOUNT_TIER_1_PCT = 0.05
DISCOUNT_TIER_2_PCT = 0.10
EARLY_BIRD_PCT = 0.10
DEPOSIT_PCT = 0.25

KIND_FLOOR_PRICE_CENTS = {
    "BOOTH_10X10": 95000,
    "BOOTH_10X20": 175000,
    "CORNER_BOOTH": 140000,
    "ENDCAP": 160000,
    "FEATURED_ISLAND": 400000,
    "ARTIST_TABLE": 27500,
    "NONPROFIT_TABLE": 15000,
}

# Jury scoring (PRD Section 3.4)
JURY_WEIGHTS = {
    "originality": 0.35,
    "craft": 0.25,
    "category_fit": 0.25,
    "professionalism": 0.15,
}
JURY_QUORUM = 3
ACCEPT_THRESHOLD = 70.00
WAITLIST_THRESHOLD = 50.00

# Badge allocation (PRD Section 3.7)
BADGES_PER_KIND = {
    "BOOTH_10X10": 4,
    "BOOTH_10X20": 6,
    "CORNER_BOOTH": 6,
    "ENDCAP": 8,
    "FEATURED_ISLAND": 12,
    "ARTIST_TABLE": 2,
    "NONPROFIT_TABLE": 2,
}
EXTRA_BADGE_FEE_CENTS = 7500

# Renewal priority (PRD Section 3.2)
W_PRIOR_YEAR = 10
W_ON_TIME_PAYMENT = 3
W_STRIKE_POINT = -8

# Strike standing bands (PRD Section 3.2), inclusive at the lower edge
SEVERITY_POINTS = {"MINOR": 1, "MAJOR": 2, "CRITICAL": 3}
PROBATION_AT = 3
SUSPENDED_AT = 5
EVICTED_AT = 7

# Cancellation refund windows (PRD Section 3.9)
FULL_REFUND_DAYS = 60
HALF_REFUND_DAYS = 30

# Freight dock-door buffer (PRD Section 3.8)
DOCK_BUFFER_MINUTES = 15

# Logical clock startup default (PRD Section 2.5)
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"

# Reference convention timeline used by the composite fixtures
CLOCK_OPEN_SUBMIT = "2026-08-13T00:00:00Z"      # inside OPEN window, early-bird OK
CLOCK_RENEWAL_ONLY = "2026-08-06T00:00:00Z"     # renewal window, before public open
CLOCK_AFTER_EARLY_BIRD = "2026-08-22T00:00:00Z"  # inside window, past early-bird
CLOCK_JURY_REVIEW = "2026-08-26T00:00:00Z"      # at/after application_close_at
CLOCK_LIVE_START = "2026-10-15T09:00:00Z"       # == starts_at
CLOCK_AFTER_SHOW = "2026-10-19T00:00:00Z"       # past ends_at
