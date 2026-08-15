"""Domain thresholds — numeric constants named in the PRD (§3 narratives)."""

THRESHOLDS = {
    # Aging buckets (PRD §3.1): inclusive lower edges in whole days.
    "BUCKET_30_EDGE_DAYS": 30,
    "BUCKET_60_EDGE_DAYS": 60,
    "BUCKET_90_EDGE_DAYS": 90,
    "BUCKET_120_EDGE_DAYS": 120,
    # Statement cycle (PRD §3.2): due_date = liability date + index * 30 days.
    "STATEMENT_CYCLE_DAYS": 30,
    # Charity eligibility (PRD §3.3).
    "FPL_TABLE": {
        1: 1506000,
        2: 2044000,
        3: 2582000,
        4: 3120000,
        5: 3658000,
        6: 4196000,
        7: 4734000,
        8: 5272000,
    },
    "FULL_CHARITY_FPL_CAP": 200,
    "PARTIAL_CHARITY_FPL_CAP": 300,
    "SCORE_FULL_CHARITY_MIN": 700,
    "SCORE_PARTIAL_CHARITY_MIN": 550,
    # Vendor performance (PRD §3.4): twelve percent recovery floor.
    "VENDOR_MIN_RECOVERY_BPS": 1200,
    # Agency recall fee (PRD §3.5): fifteen percent, capped, rounded down.
    "RECALL_FEE_BPS": 1500,
    "RECALL_FEE_CAP_CENTS": 50000,
    # Payment plans (PRD §3.7): thirty-day cadence, two missed = default.
    "INSTALLMENT_INTERVAL_DAYS": 30,
    "PAYMENT_PLAN_DEFAULT_MISSED_THRESHOLD": 2,
    # Statement-cycle minimums gating agency placement / write-off approval.
    # The PRD names these as the configured minimums; the unit's configuration
    # used by these tests is 3 sent-or-delivered statements.
    "REQUIRED_STATEMENTS": 3,
}

TEST_DEFAULTS = {
    "BALANCE_CENTS": 100000,
    "GUARANTOR_LIABILITY_DATE": "2026-01-01",
    "COST_REPORT_YEAR": 2026,
    "EARLY_OUT_FEE_BPS": 1500,
    "AGENCY_FEE_BPS": 2000,
}

# Server boot value of the logical clock (PRD §2.4).
LOGICAL_CLOCK_START = "2026-08-01T00:00:00Z"
LOGICAL_CLOCK_START_DATE = "2026-08-01"
