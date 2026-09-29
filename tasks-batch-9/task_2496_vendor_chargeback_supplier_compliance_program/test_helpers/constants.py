"""Programme constants and the recurring fee schedules used by the tests.

Every figure here is quoted from the PRD; nothing is invented.  The requirement
fee schedules at the bottom are simply reusable request payload fragments — the
PRD fixes no particular schedule, only the arithmetic that consumes one.
"""

# --------------------------------------------------------------- logical clock
# The clock is initialised to this instant and never advances on its own.
LOGICAL_CLOCK_DEFAULT_UTC = "2026-08-01T00:00:00.000Z"

# ------------------------------------------------------------ window constants
VIOLATION_FILING_WINDOW_HOURS = 72
DISPUTE_WINDOW_DAYS = 30
DISPUTE_MAX_ROUNDS = 2
CAP_MAX_SUBMISSIONS = 2
SCORECARD_PERIOD_GAP_DAYS = 1

# -------------------------------------------------------------- money exposure
VENDOR_EXPOSURE_ALERT_CENTS = 500_000

# ------------------------------------------------------- assessment constants
GRACE_LOOKBACK_DAYS = 180

# -------------------------------------------------------- scorecard constants
OTIF_WEIGHT = 0.60
FILL_WEIGHT = 0.40
DEFAULT_TOLERANCE_EARLY_DAYS = 2
DEFAULT_TOLERANCE_LATE_DAYS = 0
DEFAULT_FILL_TOLERANCE_PCT = 2.00

# ------------------------------------------------ dispute reversal constants
REASON_CEILING_PCT = {
    "NOT_OUR_LABEL": 100.00,
    "CARRIER_CAUSED": 60.00,
    "DUPLICATE_ASSESSMENT": 100.00,
    "FEE_MISCALCULATED": 100.00,
    # EVIDENCE_INSUFFICIENT resolves to 100.00 when the assessment-time evidence
    # snapshot was strictly below min_evidence_count, and 50.00 otherwise.
    "EVIDENCE_INSUFFICIENT_UNDER_MINIMUM": 100.00,
    "EVIDENCE_INSUFFICIENT_AT_OR_ABOVE_MINIMUM": 50.00,
}
GOODWILL_PCT = 25
GOODWILL_OTIF_THRESHOLD = 95.00

# ------------------------------------------------- repeat offender escalation
REPEAT_LOOKBACK_DAYS = 180
REPEAT_VIOLATION_THRESHOLD = 3
REPEAT_TIER1_SCORE = 90.00
CAP_TRIGGER_SCORE = 92.00
CRITICAL_SCORE = 80.00
CAP_DUE_DAYS_BY_LEVEL = {1: 30, 2: 21, 3: 14}
MAX_ESCALATION_LEVEL = 3

# ------------------------------------------------------------------ paging
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0

# ------------------------------------------------------ recurring test values
CLOCK_PROGRAMME_START = "2026-08-01T00:00:00Z"
CLOCK_RECEIPT_DAY = "2026-08-10T00:00:00Z"
GUIDE_EFFECTIVE_FROM = "2026-08-05T00:00:00Z"

# Reusable requirement fee schedules (request payload fragments).
REQ_SHP_04 = {
    "requirement_code": "SHP-04",
    "domain": "SHIPMENT",
    "severity_tier": "TIER_1",
    "min_evidence_count": 2,
    "fixed_fee_cents": 200_000,
    "per_unit_recovery_cents": 500,
    "handling_pct": 5.00,
    "min_fee_cents": 100_000,
    "cap_cents": 900_000,
}
REQ_LBL_01 = {
    "requirement_code": "LBL-01",
    "domain": "LABELING",
    "severity_tier": "TIER_1",
    "min_evidence_count": 2,
    "fixed_fee_cents": 25_000,
    "per_unit_recovery_cents": 30,
    "handling_pct": 2.00,
    "min_fee_cents": 30_000,
    "cap_cents": 40_000,
}
REQ_PKG_02 = {
    "requirement_code": "PKG-02",
    "domain": "PACKAGING",
    "severity_tier": "TIER_2",
    "min_evidence_count": 1,
    "fixed_fee_cents": 20_000,
    "per_unit_recovery_cents": 25,
    "handling_pct": 3.00,
    "min_fee_cents": 45_000,
    "cap_cents": 400_000,
}
REQ_DOC_03 = {
    "requirement_code": "DOC-03",
    "domain": "DOCUMENTATION",
    "severity_tier": "TIER_3",
    "min_evidence_count": 0,
    "fixed_fee_cents": 15_000,
    "per_unit_recovery_cents": 10,
    "handling_pct": 1.00,
    "min_fee_cents": 15_000,
    "cap_cents": 100_000,
}
