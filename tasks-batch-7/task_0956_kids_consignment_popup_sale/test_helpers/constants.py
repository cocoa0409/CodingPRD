"""Domain thresholds — numeric constants named by PRD §3 rules."""

PRICE = {
    # PRD §3.3: tag price floor and increment
    "MIN_CENTS": 200,
    "INCREMENT_CENTS": 50,
}

MARKDOWN = {
    # PRD §3.1: discount_pct integer between 1 and 90
    "MIN_PCT": 1,
    "MAX_PCT": 90,
    # PRD §3.9: provisional projection assumes half of remaining ON_FLOOR
    # inventory sells at the current markdown price
    "SELL_THROUGH_PCT": 50,
}

VOLUNTEER_TIERS = {
    # PRD §3.6: inclusive-boundary ladder on completed hours
    "HOURS_12": 12,
    "HOURS_8": 8,
    "HOURS_4": 4,
    "PCT_12H": 20,
    "PCT_8H": 15,
    "PCT_4H": 10,
    "BASE_PCT": 5,
}

SPLIT = {
    # PRD §3.9: three-tier consignor split ladder plus volunteer bonus and cap
    "TIER_LOW_MAX_CENTS": 20000,
    "TIER_MID_MAX_CENTS": 50000,
    "LOW_PCT": 60,
    "MID_PCT": 65,
    "HIGH_PCT": 70,
    "VOLUNTEER_BONUS_PCT": 5,
    "BONUS_HOURS_THRESHOLD": 4,
    "CAP_PCT": 75,
}

FEES = {
    # PRD §3.9: payout pipeline fee constants
    "SUPPLY_FEE_CENTS": 1000,
    "FEE_WAIVER_PAYOUT_THRESHOLD_CENTS": 30000,
    "REJECTED_ITEM_FEE_CENTS": 200,
}

CLOCK = {
    # PRD §2.5: startup default of the logical clock
    "STARTUP_DEFAULT": "2026-05-01T00:00:00Z",
}
