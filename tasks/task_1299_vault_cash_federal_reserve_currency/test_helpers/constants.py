"""Domain thresholds — numeric constants named by the PRD."""

THRESHOLDS = {
    # PRD §3.2: each strap holds 100 notes.
    "STRAP_NOTES": 100,
    # PRD §3.2: service fee is one one-hundred-sixtieth of the line value (0.625%).
    "FEE_NUM": 1,
    "FEE_DEN": 160,
    # PRD §3.7: weighted-average trailing weights.
    # (0.5 / 0.3 / 0.2 on w1 / w2 / w3)
    # PRD §3.7: recommended load rounds up to whole 2,000-dollar straps.
    "ATM_LOAD_STRAP_CENTS": 200000,
    # PRD §3.7: residual target floor is 1,000 dollars; 15% of projected final.
    "MIN_RESIDUAL_CENTS": 100000,
    "RESIDUAL_PCT_BPS": 1500,
    # PRD §2.9: ELEVATED at exactly 90.000% utilization of the vault limit.
    "ELEVATED_NUM": 9,
    "ELEVATED_DEN": 10,
    # PRD §3.6 / §2.9: SEIZED case ages into ELEVATED after 5 days, FROZEN after 10.
    "REPORT_OVERDUE_DAYS": 5,
    "SEIZED_FREEZE_DAYS": 10,
    # PRD §3.5: shrink settle tolerance — exactly 500 settles, 501 rejected.
    "SHRINK_TOLERANCE_CENTS": 500,
    # PRD §3.8: auto-fork tolerance on the count variance.
    "RECON_TOLERANCE_CENTS": 1000,
    # PRD §3.4: carrier turnaround buffer and dock arrival window half-width.
    "TURNAROUND_BUFFER_MINUTES": 45,
    "DOCK_WINDOW_MINUTES": 30,
    # PRD §3.2: valid note face values.
    "VALID_DENOMINATIONS": (100, 200, 500, 1000, 2000, 5000, 10000),
}

TEST_DEFAULTS = {
    # Default logical clock before any admin call (PRD §2.4).
    "CLOCK_START_ISO": "2026-08-01T00:00:00Z",
    "VAULT_LIMIT_CENTS": 100000000,
    "INSURANCE_COVERAGE_CENTS": 100000000,
    "DOCK_CAPACITY": 2,
    "CARRIER_LIABILITY_CAP_CENTS": 50000000,
    "ATM_CAPACITY_CENTS": 10000000,
}
