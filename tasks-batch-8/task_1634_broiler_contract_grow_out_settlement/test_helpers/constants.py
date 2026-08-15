"""Domain thresholds — numeric constants from the PRD's calculation rules."""

THRESHOLDS = {
    # Feed-waste credit subtracted before the adjusted FCR division (PRD §3.5).
    "FEED_WASTE_CREDIT_LBS": 2000,
    # Minimum flock age in days at catch scheduling (PRD §3.5).
    "MIN_GROW_DAYS": 35,
    # House resting window after a completed catch (PRD §3.4/§3.5).
    "DOWNTIME_DAYS": 14,
    # House rest after a whole-flock condemned-loss declaration (PRD §3.6).
    "CONDEMNED_LOSS_DOWNTIME_DAYS": 21,
    # Whole-flock loss threshold: condemnation_pct must strictly exceed it (PRD §3.6).
    "CONDEMNATION_LOSS_THRESHOLD": 0.30,
    # Condemnation allowance and per-pound deduction rate (PRD §3.8).
    "CONDEMNATION_ALLOWANCE": 0.005,
    "CONDEMNATION_RATE_CENTS": 40,
    # Rolling window for the grower performance rating (PRD §3.10).
    "RATING_WINDOW": 3,
    # Loan recovery percentage bounds (PRD §3.9).
    "RECOVERY_PCT_MIN": 1,
    "RECOVERY_PCT_MAX": 50,
    # Minimum quarantine days on a FAIL audit (PRD §3.4).
    "MIN_QUARANTINE_DAYS_ON_FAIL": 7,
}

TEST_DEFAULTS = {
    "BASE_PAY_CENTS_PER_LB": 6,
    "CAPACITY_BIRDS": 10000,
    "PLACED_HEAD": 5000,
    "FEED_LBS": 10000,
    "LIVE_WEIGHT_LBS": 5000,
    "TERM_START_DATE": "2026-01-01",
    "TERM_END_DATE": "2027-01-01",
    "PLACED_DATE": "2026-08-01",
    "CATCH_DATE": "2026-09-10",
    "WEEK_ENDING_DATE": "2026-12-31",
}

# Fixed startup instant of the server logical clock (PRD §2.9).
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"
