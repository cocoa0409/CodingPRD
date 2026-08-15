"""Domain thresholds and logical-clock constants (PRD sections 2.4, 3.4, 3.7, 3.9)."""

# The logical clock's startup value (PRD section 2.4).
DEFAULT_NOW_UTC = "2026-08-01T00:00:00Z"

THRESHOLDS = {
    # Dunning: five failures is exhaustion (PRD section 3.4).
    "DUNNING_MAX_ATTEMPTS": 5,
    # Save offers live exactly 72 hours (PRD section 3.6).
    "SAVE_OFFER_TTL_HOURS": 72,
    # Price change effective date must be >= 30 days after announcement (PRD section 3.7).
    "PRICE_CHANGE_MIN_NOTICE_DAYS": 30,
    # Auto-reconcile tolerance in cents; |delta| == 500 reconciles (PRD section 3.9).
    "AUTO_RECONCILE_TOLERANCE_CENTS": 500,
    # Direct-pause cooldown window in months (PRD section 3.5).
    "PAUSE_COOLDOWN_MONTHS": 12,
    # Nominal billing period length in days (PRD section 3.2).
    "DAYS_PER_PERIOD_NOMINAL": 30,
}

TEST_DEFAULTS = {
    "PLAN_CODE": "BASIC",
    "PLAN_DISPLAY_NAME": "Basic",
    "PLAN_TIER": "BASIC",
    "PLAN_MONTHLY_PRICE_CENTS": 3000,
    "PLAN_TRIAL_DAYS": 0,
    "PLAN_MAX_PROFILES": 2,
    "PLAN_MAX_HOUSEHOLDS": 1,
    "ACCOUNT_COUNTRY_CODE": "US",
    "PROFILE_HOUSEHOLD_ID": "hh-1",
}
