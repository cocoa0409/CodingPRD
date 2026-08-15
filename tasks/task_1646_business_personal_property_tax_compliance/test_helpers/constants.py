"""Domain thresholds and fixed values named in the PRD's calculation narratives."""

THRESHOLDS = {
    # Exemption credit is capped at fifty percent of the gross tax (PRD §3.6 step two).
    "EXEMPTION_TAX_CAP_PCT": 50,
    # |variance| of no more than 100 cents lands the bill in MATCHED (PRD §3.6).
    "VARIANCE_TOLERANCE_CENTS": 100,
    # Installment count bounds (PRD §3.6).
    "MAX_INSTALLMENTS": 4,
    "INSTALLMENT_SPACING_DAYS": 30,
    # Each started thirty-day month of lateness counts as one penalty month (PRD §3.4).
    "DAYS_PER_PENALTY_MONTH": 30,
    # RENDERED_CONSERVATIVE uplift on rendered values (PRD §3.8).
    "UPLIFT_PCT": 10,
    # Suspended exemptions are revoked after the ninety-day cure period (PRD §3.7).
    "EXEMPTION_CURE_DAYS": 90,
}

# The logical clock starts at exactly this instant before any clock-setting call (PRD §2.5).
DEFAULT_LOGICAL_CLOCK = "2026-08-01T00:00:00Z"
DEFAULT_LOGICAL_CLOCK_DATE = "2026-08-01"

TEST_DEFAULTS = {
    "TAX_YEAR": 2027,
    "BASE_DEADLINE_MMDD": "04-15",
    "DEADLINE_DATE_2027": "2027-04-15",
    "MAX_EXTENSION_DAYS": 30,
    "LATE_PENALTY_PCT_PER_MONTH": 2,
    "MAX_LATE_PENALTY_PCT": 10,
    "JURISDICTION_TAX_RATE": 0.02,
    "BILL_TAX_RATE": 0.025,
    "NOTICE_VALUE_CENTS": 800000,
    "BILLED_AMOUNT_CENTS": 20000,
    "BILL_DUE_DATE": "2027-06-30",
    "RECEIVED_DATE": "2027-05-01",
    "PROTEST_DEADLINE_DATE": "2027-05-31",
    "FORECAST_AS_OF_DATE": "2027-03-01",
}
