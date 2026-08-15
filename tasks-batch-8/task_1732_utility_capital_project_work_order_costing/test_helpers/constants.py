"""Domain thresholds and shared constants (PRD §2.6, §3.3-§3.9)."""

THRESHOLDS = {
    # PRD §3.3: authorize tier — strictly below 10,000,000 cents a supervisor
    # may authorize; at or above, only a Controller.
    "AUTHORIZE_CONTROLLER_THRESHOLD_CENTS": 10_000_000,
    # PRD §3.4: estimate decision routes to CONTROLLER when |delta|*100 reaches
    # or exceeds current approved * 10 (inclusive boundary).
    "REESTIMATE_CONTROLLER_PCT": 10,
    # PRD §3.5: variance posture flips only when actuals*100 is strictly
    # greater than approved*110.
    "VARIANCE_BLOCK_PCT": 110,
    # PRD §3.7: ten percent forfeiture on CIAC refunds from IN_PROGRESS /
    # SUSPENDED cancellations.
    "FORFEIT_PCT": 10,
    # PRD §3.8: closeout variance tolerance is fifteen percent of the approved
    # estimate.
    "CLOSEOUT_TOLERANCE_PCT": 15,
}

# PRD §2.6: before it has ever been set, the logical clock reads exactly
# 2026-08-01T00:00:00Z.
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

TEST_DEFAULTS = {
    # Program AFUDC parameters that yield a composite 1%/month rate:
    # (100 * 12.0 + 0 * 0.0) / 100 / 12 == 1.0
    "AFUDC_DEBT_RATE_PCT": 12.0,
    "AFUDC_EQUITY_RATE_PCT": 0.0,
    "AFUDC_DEBT_WEIGHT_PCT": 100,
    "AFUDC_METHOD": "HALF_MONTH",
    "CIAC_METHOD": "NET_OF_CIAC",
    "AUTHORIZED_AMOUNT_CENTS": 100_000_000,
    "FISCAL_YEAR": 2026,
}

# Standard first accounting period used by most scenarios (PRD §3.2: the first
# period of the calendar may begin on any date).
PERIOD_2026_08 = {
    "fiscal_year": 2026,
    "period_no": 8,
    "start_date": "2026-08-01",
    "end_date": "2026-08-31",
}
PERIOD_2026_09 = {
    "fiscal_year": 2026,
    "period_no": 9,
    "start_date": "2026-09-01",
    "end_date": "2026-09-30",
}
PERIOD_2026_10 = {
    "fiscal_year": 2026,
    "period_no": 10,
    "start_date": "2026-10-01",
    "end_date": "2026-10-31",
}

# A far-future CIAC pledge expiry that never trips in ordinary scenarios.
CIAC_FAR_EXPIRY = "2026-12-31T00:00:00Z"
