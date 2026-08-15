"""Domain thresholds — numeric constants from PRD §2.5 and §3."""

INCEPTION_UNIT_PRICE_MILLICENTS = 100_000  # $1.000 per unit at pool inception (PRD §2.5)
MIN_ENDOWMENT_CORPUS_CENTS = 5_000_000     # $50,000.00 activation minimum (PRD §3.1)
LAPSE_QUARTERS = 4                         # payout unspent sweep age (PRD §3.7)
QUARTER_DAYS = 90                          # every quarter is exactly 90 days (PRD §2.5)
QUARTERS_PER_FISCAL_YEAR = 4               # FY k covers quarters 4k+1..4k+4 (PRD §2.5)
UNIT_SCALE = 1_000_000                     # 1 unit = 1e6 micro-units (PRD §2.4)
PRICE_SCALE = 1_000                        # 1 cent = 1000 millicents (PRD §2.4)

THRESHOLDS = {
    "INCEPTION_UNIT_PRICE_MILLICENTS": INCEPTION_UNIT_PRICE_MILLICENTS,
    "MIN_ENDOWMENT_CORPUS_CENTS": MIN_ENDOWMENT_CORPUS_CENTS,
    "LAPSE_QUARTERS": LAPSE_QUARTERS,
    "QUARTER_DAYS": QUARTER_DAYS,
    "SPENDING_RATE_BPS_MIN": 100,
    "SPENDING_RATE_BPS_MAX": 2000,
    "SMOOTHING_WINDOW_MIN": 4,
    "SMOOTHING_WINDOW_MAX": 20,
    "ALLOCATION_TARGET_SUM_BPS": 10_000,
    "WATCHLIST_NEG_STREAK": 3,
    "PROBATION_NEG_STREAK": 6,
    "RECOVERY_NONNEG_STREAK": 2,
}

TEST_DEFAULTS = {
    "INCEPTION_FY": 2026,
    "CORPUS_GIFT_CENTS": 10_000_000,
    "POLICY_RATE_BPS": 500,
    "POLICY_WINDOW": 4,
}
