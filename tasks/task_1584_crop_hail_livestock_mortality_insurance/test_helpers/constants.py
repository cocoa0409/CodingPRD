"""Domain thresholds and numeric constants stated in the PRD."""

THRESHOLDS = {
    # PRD §2.7: fixed per-acre exposure constant ($400.00 per acre).
    "USD_CENTS_PER_ACRE": 40_000,
    # PRD §3.4: premium reserve is 60% of the frozen premium, rounded down.
    "RESERVE_RATIO": 0.60,
    # PRD §3.4/§3.9: continuous-coverage carryover credit = 5% of prior premium
    # when the gap is at most 7 days.
    "CARRYOVER_PCT": 5,
    "MAX_CONTINUITY_GAP_DAYS": 7,
    # PRD §3.7: necropsy gate for livestock claims appraised over $5,000.
    "NECROPSY_THRESHOLD_CENTS": 500_000,
    # PRD §3.3: dual-coverage offset is 20% of the federal liability.
    "DUAL_COVERAGE_OFFSET_PCT": 20,
    # PRD §3.7: notice windows in hours.
    "NOTICE_WINDOW_HAIL_HOURS": 72,
    "NOTICE_WINDOW_LIVESTOCK_HOURS": 24,
    # PRD §3.7: late-notice penalty tiers.
    "LATE_NOTICE_TIER1_DAYS": 7,
    "LATE_NOTICE_TIER1_PCT": 10,
    "LATE_NOTICE_TIER2_DAYS": 30,
    "LATE_NOTICE_TIER2_PCT": 25,
    # PRD §3.6: delinquency 30 days after binding while underpaid.
    "DELINQUENCY_DAYS": 30,
    # PRD §3.8: void window.
    "VOID_WINDOW_HOURS": 24,
    # PRD §3.4: high-risk surcharge tiers (inclusive boundaries).
    "SURCHARGE_TIER1_MIN_CLAIMS": 2,
    "SURCHARGE_TIER1_PCT": 10,
    "SURCHARGE_TIER2_MIN_CLAIMS": 4,
    "SURCHARGE_TIER2_PCT": 25,
    # PRD §3.5: coverage reduction per late day, capped.
    "COVERAGE_REDUCTION_PER_LATE_DAY_PCT": 5,
    "COVERAGE_REDUCTION_CAP_PCT": 100,
}

# PRD §2.5: the carrier logical clock starts here.
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

# Shared test geography / rating defaults.
TEST_DEFAULTS = {
    "COUNTY_CODE": "06001",
    "STATE_CODE": "CA",
    "CROP_CODE": "CORN",
    "RATE_PER_100": 333,
    "REINSURANCE_ATTACHMENT_CENTS": 100_000_000,
    "RATE_EFFECTIVE_FROM": "2026-01-01T00:00:00Z",
    "POLICY_EFFECTIVE": "2026-08-02T00:00:00Z",
    "POLICY_EXPIRATION": "2026-12-31T00:00:00Z",
    "ACTIVATE_CLOCK": "2026-08-03T00:00:00Z",
    "LOSS_DATE": "2026-08-04T00:00:00Z",
}
