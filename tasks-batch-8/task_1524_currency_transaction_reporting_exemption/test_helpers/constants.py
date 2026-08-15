"""Domain thresholds — numeric constants pinned by the PRD's calculations."""

CTR_THRESHOLD_CENTS = 1_000_000           # strictly greater-than threshold
EFILE_DEADLINE_DAYS = 15                  # business_date + 15 calendar days
PAPER_DEADLINE_DAYS = 25                  # business_date + 25 calendar days
AMENDMENT_WINDOW_DAYS = 45                # current date <= business_date + 45
EXEMPTION_REVIEW_PERIOD_DAYS = 365        # review_due_date offset

FEE_BPS = 50                              # 50 basis points
FEE_DENOMINATOR = 10_000                  # amount * 50 / 10000
MIN_FEE_CENTS = 150                       # per-instrument floor

INSTRUMENT_RECORD_BAND_LOW = 300_000      # inclusive
INSTRUMENT_RECORD_BAND_HIGH = 1_000_000   # inclusive
MONEY_ORDER_MAX_CENTS = 100_000           # inclusive

PHASE_II_MIN_QUALIFYING_DAYS = 5
PHASE_II_MIN_ACCOUNT_AGE_DAYS = 60
ELIGIBILITY_WINDOW_DAYS = 365

STRUCTURING_WINDOW_DAYS = 5
STRUCTURING_THRESHOLD_CENTS = 1_000_000   # strictly greater
NEAR_THRESHOLD_LOW_CENTS = 900_000        # inclusive band [900000, 1000000]
SCORE_BASE = 40
SCORE_PER_BRANCH = 8
SCORE_PER_DAY = 6
SCORE_NEAR_THRESHOLD = 15
SCORE_PER_PRIOR_REFERRAL = 10
SCORE_CAP = 100

GENESIS_HASH = "0" * 64
CLOCK_DEFAULT_START = "2026-08-01T00:00:00Z"
