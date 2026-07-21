"""Domain thresholds and shared test literals drawn from the PRD narrative."""

# Thresholds named in the PRD's calculations and rules.
THRESHOLDS = {
    # §3.2 fifteen-minute turnover buffer between holds on the same table.
    "TABLE_HOLD_BUFFER_MINUTES": 15,
    # §3.3 early-bird cutoff is event_start_utc less 30 days.
    "EARLY_BIRD_DAYS_BEFORE_EVENT": 30,
    "EARLY_BIRD_TABLE_DISCOUNT_RATE": 0.15,
    "EARLY_BIRD_SEAT_DISCOUNT_RATE": 0.10,
    # §3.3 non-deductible dinner benefit per seat.
    "DINNER_BENEFIT_PER_SEAT_CENTS": 7_500,
    # §3.7 processing-fee tiers, selected from the pre-fee subtotal.
    "FEE_TIER_1_CEILING_CENTS": 50_000,
    "FEE_TIER_2_CEILING_CENTS": 500_000,
    "FEE_RATE_TIER_1": 0.029,
    "FEE_RATE_TIER_2": 0.024,
    "FEE_RATE_TIER_3": 0.019,
    "FEE_FLAT_CENTS": 30,
    # §3.6 dollar-for-dollar challenge match.
    "MATCH_RATIO": 1.0,
    # §3.8 de-minimis benefit threshold.
    "DE_MINIMIS_BENEFIT_CENTS": 1_500,
    # §3.9 material-variance threshold, inclusive.
    "MATERIAL_VARIANCE_CENTS": 5_000,
    # §3.10 pledge grace window.
    "PLEDGE_LAPSE_GRACE_DAYS": 30,
    # §3.4 program-ad revision budget.
    "MAX_AD_REVISIONS": 2,
    # §2.3 pagination.
    "DEFAULT_PAGE_LIMIT": 10,
    "MAX_PAGE_LIMIT": 100,
}

# §2.8 the logical clock's startup instant.
CLOCK_STARTUP_UTC = "2026-07-01T00:00:00Z"

# Shared scenario literals reused across fixtures and tests.
TEST_DEFAULTS = {
    "EVENT_NAME": "Harbor Light Gala",
    "EVENT_START_UTC": "2026-09-12T23:00:00Z",
    "EVENT_END_UTC": "2026-09-13T04:00:00Z",
    # event_start_utc less 30 days.
    "EARLY_BIRD_CUTOFF_UTC": "2026-08-13T23:00:00Z",
    "PRE_CUTOFF_CLOCK_UTC": "2026-07-05T00:00:00Z",
    "POST_CUTOFF_CLOCK_UTC": "2026-08-20T00:00:00Z",
    "TABLE_NAME": "T1",
    "TABLE_SEAT_COUNT": 10,
    "TABLE_PRICE_CENTS": 1_250_000,
    "SEAT_PRICE_CENTS": 12_533,
    "MATCH_CAP_CENTS": 500_000,
    "SPONSOR_COMMITMENT_CENTS": 250_000,
    "LOT_OPEN_AT_UTC": "2026-07-04T00:00:00Z",
    "LOT_CLOSE_AT_UTC": "2026-07-30T00:00:00Z",
    "STARTING_BID_CENTS": 10_000,
    "MIN_INCREMENT_CENTS": 500,
    "ESTIMATED_FMV_CENTS": 4_000,
}

# Operator identifiers for the three opaque roles.
ORG_USER_ID = "org-1"
AUCTION_USER_ID = "auc-1"
FINANCE_USER_ID = "fin-1"
FINANCE_USER_ID_2 = "fin-2"
