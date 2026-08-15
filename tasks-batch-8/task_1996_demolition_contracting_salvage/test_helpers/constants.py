"""Domain thresholds — numeric constants from PRD §2.5 and §3 calculations."""

# PRD §2.5: recurring threshold constants.
THRESHOLDS = {
    # dust exposure: exceedance at score >= 75.0; raw figure capped at 1000
    "DUST_EXCEEDANCE_THRESHOLD": 75.0,
    "DUST_RAW_CAP": 1000.0,
    # diversion tiers split at 0.7500 (GOLD) and 0.5000 (SILVER)
    "DIVERSION_TIER_GOLD": 0.75,
    "DIVERSION_TIER_SILVER": 0.5,
    # final erosion coverage must reach 0.9000
    "MIN_FINAL_COVERAGE": 0.9,
    # permit validity is 90 days; renewal extends by 90 days
    "PERMIT_VALIDITY_DAYS": 90,
    # neighbor-notification wait window is 72 hours
    "NOTIFICATION_WAIT_HOURS": 72,
    # no more than three deliveries per project per UTC date
    "DAILY_DELIVERY_CAP": 3,
    # reconcile corrections tolerate at most 2.0 tons
    "RECONCILE_DELTA_CAP_TONS": 2.0,
    # delivery occupation window is 30 minutes
    "DELIVERY_OCCUPATION_MINUTES": 30,
}

# PRD §3.3: tiered permit fee schedule (integer cents).
PERMIT_FEE = {
    "BASE_FEE_CENTS": 150000,
    "BASE_RATE_CENTS": 12,
    "TIER2_THRESHOLD_CENTS": 500000,
    "TIER1_RATE_CENTS": 12,
    "TIER2_RATE_CENTS": 18,
    "TIER2_SURCHARGE_CENTS": 25000,
}

# PRD §3.8: wind multiplier tiers for dust exposure scoring.
WIND_FACTOR_TIERS = {
    "LOW_MAX_EXCLUSIVE": 5.0,      # wind < 5        -> 0.5
    "MID_MAX_INCLUSIVE": 12.0,     # 5 <= wind <= 12 -> 1.0
    "HIGH_MAX_INCLUSIVE": 20.0,    # 12 < wind <= 20 -> 1.6
    # wind > 20                          -> 2.4
    "FACTOR_LOW": 0.5,
    "FACTOR_MID": 1.0,
    "FACTOR_HIGH": 1.6,
    "FACTOR_EXTREME": 2.4,
}

TEST_DEFAULTS = {
    "LOT_AREA_SQFT": 30000,
    "PERMIT_AREA_SQFT": 20000,
    "REQUIRED_DIVERSION_RATE": 0.5,
    # standard window used by release-chain fixtures (PRD §3.6 quiet hours are
    # [19:00, 07:00) UTC, so 08:00-12:00 UTC windows are always deliverable)
    "WINDOW_START": "2026-08-02T08:00:00Z",
    "WINDOW_END": "2026-08-02T12:00:00Z",
    "CLOCK_INIT": "2026-08-01T09:00:00Z",
    "CLOCK_DELIVER": "2026-08-02T09:00:00Z",
    "CLOCK_RELEASE": "2026-08-05T09:00:00Z",
}
