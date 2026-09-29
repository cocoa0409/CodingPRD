"""Domain thresholds and canonical test data, taken from the PRD narratives."""

THRESHOLDS = {
    # Press windows are half-open and carry a 45-minute changeover allowance.
    "CHANGEOVER_BUFFER_MINUTES": 45,
    # A press may not be booked past 1,224 minutes of committed time on any
    # single UTC calendar day.
    "PRESS_DAILY_CAPACITY_MINUTES": 1224,
    # A run-at-rate achievement of at least 9,000 basis points qualifies.
    "RUN_AT_RATE_MIN_BP": 9000,
    # A resin lot may be released only at or below 200 basis points of moisture.
    "MAX_MOISTURE_BP": 200,
    # The first-article sample must have been drawn from a run of >= 30 shots.
    "MIN_FAI_SAMPLE_SHOTS": 30,
    # The shop's default regrind ceiling when the tool has no approved package.
    "DEFAULT_MAX_REGRIND_BP": 1500,
    # The shop's standard yield used by the quoted estimate.
    "STANDARD_YIELD_BP": 9700,
    # The quoted lot is a fixed 1,000 parts, packaged at a flat rate.
    "LOT_PARTS": 1000,
    "PACKAGING_CENTS_PER_LOT": 1800,
    "TOOLING_AMORTISATION_LOTS": 50,
    "MIN_PIECE_PRICE_CENTS": 12,
    # Margin tiers keyed on annual_volume.
    "MARGIN_BP_LOW_VOLUME": 2800,
    "MARGIN_BP_MID_VOLUME": 2200,
    "MARGIN_BP_HIGH_VOLUME": 1600,
    # Overhead tiers keyed on job_direct_cost_cents before overhead is added.
    "OVERHEAD_BP_LOW": 3500,
    "OVERHEAD_BP_MID": 2800,
    "OVERHEAD_BP_HIGH": 2200,
    # Capacity commitments: assumed press availability and goodwill waiver.
    "PRESS_AVAILABILITY_BP": 8500,
    "GOODWILL_WAIVER_BP": 1000,
    "GOODWILL_RATE_BP": 5000,
    "BASIS_POINTS_FULL": 10000,
}

# The logical clock reads exactly this instant before any caller moves it.
CLOCK_EPOCH = "2026-08-01T00:00:00Z"

TEST_DEFAULTS = {
    "CLOCK": "2026-09-01T00:00:00Z",
    "CUSTOMER_NAME": "Acme Controls",
    "CUSTOMER_CODE": "ACME",
    "SECOND_CUSTOMER_NAME": "Beta Devices",
    "SECOND_CUSTOMER_CODE": "BETA",
    "PRESS_CODE": "P-150",
    "PRESS_TONNAGE": 150,
    "PRESS_SHOT_SIZE_GRAMS_MAX": 400,
    "PRESS_HOURLY_RATE_CENTS": 7200,
    "MOLD_CODE": "M-1",
    "MOLD_CAVITY_COUNT": 4,
    "MOLD_SHOT_WEIGHT_GRAMS": 180,
    "MOLD_MIN_TONNAGE": 120,
    "MOLD_MAX_TONNAGE": 200,
    "MOLD_PM_INTERVAL_SHOTS": 5000,
    "MOLD_TOOLING_COST_CENTS": 2500000,
    "TRIAL_START": "2026-09-02T08:00:00Z",
    "TRIAL_END": "2026-09-02T12:00:00Z",
    "TRIAL_TARGET_PARTS_PER_HOUR": 400,
    "TRIAL_PASSING_PARTS_PER_HOUR": 380,
    "TRIAL_FAILING_PARTS_PER_HOUR": 300,
    "QUOTE_PART_WEIGHT_GRAMS": 32,
    "QUOTE_CYCLE_TIME_SEC": 38,
    "QUOTE_CAVITATION": 4,
    "QUOTE_RESIN_GRADE": "PP-H",
    "QUOTE_RESIN_PRICE_CENTS_PER_KG": 210,
    "QUOTE_ANNUAL_VOLUME": 120000,
    "PPAP_LEVEL": 3,
    "PPAP_MAX_REGRIND_BP": 2000,
    "PPAP_FAI_SAMPLE_SHOTS": 30,
    "LOT_CODE": "L-77",
    "LOT_QTY_KG": 500,
    "LOT_MOISTURE_BP": 120,
    "JOB_START": "2026-09-10T08:00:00Z",
    "JOB_END": "2026-09-10T16:00:00Z",
    "JOB_PLANNED_QTY": 20000,
}
