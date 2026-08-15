"""Domain thresholds — numeric constants from PRD §2.8 and §2.9."""

# PRD §2.8: one cfs sustained for one hour yields 0.0826 acre-feet.
AF_PER_CFS_HOUR = 0.0826

# PRD §2.8: turnaround gap between non-terminal orders of one account;
# exactly 6 hours is permitted.
TURNAROUND_MIN_GAP_HOURS = 6

# PRD §2.8: delinquency grace and late penalty.
GRACE_DAYS = 10
LATE_PENALTY_PCT = 10

# PRD §2.9: seniority cut date (inclusive) and drought stage percentages.
PRIORITY_CUT_DATE = "1914-12-31"
DROUGHT_STAGES = {
    "STAGE_1": {"senior": 0, "junior": 15},
    "STAGE_2": {"senior": 10, "junior": 40},
    "STAGE_3": {"senior": 25, "junior": 75},
}

THRESHOLDS = {
    "AF_PER_CFS_HOUR": AF_PER_CFS_HOUR,
    "TURNAROUND_MIN_GAP_HOURS": TURNAROUND_MIN_GAP_HOURS,
    "GRACE_DAYS": GRACE_DAYS,
    "LATE_PENALTY_PCT": LATE_PENALTY_PCT,
}

# Shared season geometry used across tests (all PRD-conformant values).
SEASON_DEFAULTS = {
    "year": 2026,
    "announced_af_per_acre": 2.0,
    "carryover_cap_pct": 50,
    "billing_method": "PER_ACRE",
    "assessment_rate_per_acre": 25.00,
    "toll_tier1_cap_af": 20.0,
    "toll_tier1_rate_per_af": 18.00,
    "toll_tier2_rate_per_af": 30.00,
    "overage_rate_per_af": 60.00,
    "start_date": "2026-04-01T00:00:00Z",
    "end_date": "2026-09-30T00:00:00Z",
}

TEST_DEFAULTS = {
    "IRRIGATED_ACRES": 5.0,
    "SENIOR_PRIORITY_DATE": "1888-01-01T00:00:00Z",
    "JUNIOR_PRIORITY_DATE": "1922-05-01T00:00:00Z",
    "REACH_CAPACITY_CFS": 50.0,
    "ORDER_START": "2026-06-01T08:00:00Z",
    "ORDER_END": "2026-06-01T18:00:00Z",
    "INVOICE_DUE_DATE": "2026-08-10T00:00:00Z",
}
