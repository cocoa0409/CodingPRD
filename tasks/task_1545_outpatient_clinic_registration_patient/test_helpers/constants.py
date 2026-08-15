"""Domain thresholds — numeric constants from PRD calculations (§2.5, §3.2, §3.5, §3.6)."""

THRESHOLDS = {
    # PRD §2.5: before it is ever set, the logical clock reads exactly this instant.
    "DEFAULT_LOGICAL_CLOCK": "2026-08-01T00:00:00Z",
    # PRD §3.2: a check exactly thirty days old is still fresh; strictly more flips STALE.
    "ELIGIBILITY_STALENESS_DAYS": 30,
    # PRD §3.6: check-in rejected once current time passes thirty minutes after start.
    "LATE_ARRIVAL_CUTOFF_MINUTES": 30,
    # PRD §3.5: at least two strikes -> 100% deposit; NEW -> 50%; other -> 25%.
    "HIGH_RISK_STRIKE_THRESHOLD": 2,
    "HIGH_RISK_DEPOSIT_PCT": 1.00,
    "NEW_VISIT_DEPOSIT_PCT": 0.50,
    "STANDARD_DEPOSIT_PCT": 0.25,
    # PRD §3.5: trailing 365-day half-open strike window.
    "STRIKE_WINDOW_DAYS": 365,
    # PRD §3.5 FEE_SCHEDULE flat base fees by visit_type.
    "FEE_SCHEDULE_NEW_CENTS": 22000,
    "FEE_SCHEDULE_ESTABLISHED_CENTS": 14000,
    "FEE_SCHEDULE_PROCEDURE_CENTS": 45000,
    "FEE_SCHEDULE_IMAGING_CENTS": 38000,
    "NEW_PATIENT_LOADING": 1.2,
}

TEST_DEFAULTS = {
    "OOP_MAX_REMAINING_CENTS": 500000,
    "DEDUCTIBLE_REMAINING_CENTS": 30000,
    "ALLOWED_AMOUNT_CENTS": 100000,
    "EFFECTIVE_START": "2026-01-01",
    "PAYER_ID": "PAYER1",
}
