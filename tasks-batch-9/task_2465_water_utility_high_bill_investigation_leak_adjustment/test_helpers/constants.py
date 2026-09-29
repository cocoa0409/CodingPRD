"""Domain constants for the water-utility high-bill service (PRD §2, §3)."""

# ---------------------------------------------------------------------------
# Logical clock (PRD §2.4)
# ---------------------------------------------------------------------------
CLOCK_PATH = "/_clock/set_current_utc"
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ---------------------------------------------------------------------------
# Workflow constants (PRD §3.2, §3.3, §3.4, §3.8, §3.9)
# ---------------------------------------------------------------------------
BILL_DUE_DAYS = 21
SHUTOFF_NOTICE_DAYS = 10
MAX_EVIDENCE_ROUNDS = 3
REMAND_MAX = 1
APPEAL_FILING_DAYS = 30
HEARING_MIN_NOTICE_DAYS = 10
HEARING_DOCKET_CAPACITY = 3
METER_TEST_DEPOSIT_CENTS = 3000
METER_TEST_QUARANTINE_HOURS = 48

# ---------------------------------------------------------------------------
# Calculation constants (PRD §2.9, §3.2, §3.4, §3.6, §3.8)
# ---------------------------------------------------------------------------
BASELINE_SAMPLE_COUNT = 3
BASELINE_MIN_SAMPLES = 3
ANOMALY_RATIO_THRESHOLD = 2.000
MAX_CREDIT_PCT_BP = 6000
MAX_CREDIT_CENTS = 50000
SEWER_RELIEF_BASIS_GALLONS = 8000
SEWER_RELIEF_LEAK_TYPES = ["SERVICE_LINE", "UNDERGROUND", "IRRIGATION", "POOL"]
ADJ_ROLLING_WINDOW_MONTHS = 12
SMALL_METER_MAX_INCHES = 2.0
AWWA_LOW_WEIGHT = 0.15
AWWA_MID_WEIGHT = 0.70
AWWA_HIGH_WEIGHT = 0.15
FAST_THRESHOLD_PCT = 101.50
SLOW_THRESHOLD_PCT = 98.50
DOWN_PAYMENT_MIN_BP = 2000
MAX_INSTALLMENTS = 12
MISSED_PAYMENTS_TO_DEFAULT = 2
MAX_ARRANGEMENT_REINSTATEMENTS = 1
PAST_DUE_THRESHOLD_CENTS = 5000

# ---------------------------------------------------------------------------
# The shared rate schedule used by every fixture chain (PRD §3.1)
# ---------------------------------------------------------------------------
STANDARD_RATE_SCHEDULE = {
    "code": "RS-STD-2026",
    "base_charge_cents": 1200,
    "tier1_limit_gallons": 3000,
    "tier1_rate_cents_per_kgal": 350,
    "tier2_limit_gallons": 10000,
    "tier2_rate_cents_per_kgal": 520,
    "tier3_rate_cents_per_kgal": 890,
    "summer_surcharge_bp": 1500,
    "sewer_rate_cents_per_kgal": 610,
    "sewer_cap_gallons": 12000,
    "submeter_sewer_credit_cap_gallons": 8000,
    "admin_fee_cents": 1500,
    "admin_fee_waiver_threshold_cents": 10000,
}

# Pinned charge outcomes on STANDARD_RATE_SCHEDULE, keyed by (season, gallons).
# Values are (water_charge_cents, sewer_charge_cents, total_charge_cents).
PINNED_CHARGES = {
    ("SUMMER", 4000): (2770, 2440, 5210),
    ("SUMMER", 7996): (4848, 4878, 9726),
    ("SUMMER", 8000): (4850, 4880, 9730),
    ("SUMMER", 12000): (7937, 7320, 15257),
    ("SUMMER", 40204): (36804, 7320, 44124),
    ("SUMMER", 41000): (37619, 7320, 44939),
    ("WINTER", 41000): (33480, 7320, 40800),
}

# ---------------------------------------------------------------------------
# The standard four-period SUMMER calendar (PRD §2.10)
# ---------------------------------------------------------------------------
STANDARD_PERIODS = [
    {
        "period_code": "2025-06",
        "start_date": "2025-06-01",
        "end_date": "2025-06-30",
        "season": "SUMMER",
        "rebilling_deadline_date": "2026-12-31",
    },
    {
        "period_code": "2025-07",
        "start_date": "2025-07-01",
        "end_date": "2025-07-31",
        "season": "SUMMER",
        "rebilling_deadline_date": "2026-12-31",
    },
    {
        "period_code": "2025-08",
        "start_date": "2025-08-01",
        "end_date": "2025-08-31",
        "season": "SUMMER",
        "rebilling_deadline_date": "2026-12-31",
    },
    {
        "period_code": "2026-07",
        "start_date": "2026-07-01",
        "end_date": "2026-07-31",
        "season": "SUMMER",
        "rebilling_deadline_date": "2027-01-31",
    },
]

# Read dates matching STANDARD_PERIODS: one opening read plus one period-end
# read for each of the four periods.
HISTORY_READ_DATES = ["2025-05-31", "2025-06-30", "2025-07-31", "2025-08-31"]
TARGET_READ_DATE = "2026-07-31"
INITIAL_REGISTER_VALUE = 100000
HISTORY_CONSUMPTION_GALLONS = 4000

# ---------------------------------------------------------------------------
# Enumerations (PRD §2.9, §3.1 - §3.9)
# ---------------------------------------------------------------------------
SEASONS = ["SUMMER", "WINTER"]
PERIOD_STATUSES = ["OPEN", "CLOSED", "LOCKED"]
METER_TYPES = ["POTABLE_MASTER", "IRRIGATION_SUBMETER", "BACKFLOW_FIRE_LINE"]
ACCURACY_STATUSES = ["UNTESTED", "VERIFIED_ACCURATE", "FAILED_FAST", "FAILED_SLOW"]
READ_TYPES = ["ACTUAL", "ESTIMATED", "CORRECTED"]
BILL_STATUSES = [
    "DRAFT",
    "ISSUED",
    "UNDER_INVESTIGATION",
    "ADJUSTED",
    "UPHELD_AS_BILLED",
    "REBILL_PENDING",
    "REBILLED",
]
BASELINE_ELIGIBLE_BILL_STATUSES = ["ISSUED", "ADJUSTED", "UPHELD_AS_BILLED"]
INVESTIGATION_STATUSES = [
    "OPEN",
    "EVIDENCE_REQUESTED",
    "EVIDENCE_UNDER_REVIEW",
    "EVIDENCE_EXHAUSTED",
    "DETERMINED",
    "ADJUSTMENT_PENDING",
    "APPEALED",
    "RESOLVED",
    "CLOSED_NO_ADJUSTMENT",
]
HOLD_ACTIVE_INVESTIGATION_STATUSES = [
    "OPEN",
    "EVIDENCE_REQUESTED",
    "EVIDENCE_UNDER_REVIEW",
    "EVIDENCE_EXHAUSTED",
    "DETERMINED",
    "ADJUSTMENT_PENDING",
    "APPEALED",
]
LEAK_DETERMINATIONS = [
    "UNDETERMINED",
    "CUSTOMER_SIDE_LEAK",
    "UTILITY_SIDE_LEAK",
    "METER_ERROR",
    "NO_LEAK",
    "IRRIGATION_USE",
]
LEAK_TYPES = ["SERVICE_LINE", "UNDERGROUND", "TOILET", "IRRIGATION", "POOL"]
BASELINE_REBILL_LEAK_TYPES = ["SERVICE_LINE", "UNDERGROUND"]
EXCESS_REPRICE_LEAK_TYPES = ["TOILET", "IRRIGATION", "POOL"]
VARIANTS = ["EXCESS_REPRICE", "BASELINE_REBILL"]
TEST_REQUEST_STATUSES = [
    "REQUESTED",
    "FIELD_TEST_SCHEDULED",
    "BENCH_TEST_PENDING",
    "CLOSED_PASS",
    "CLOSED_FAST",
    "CLOSED_SLOW",
]
CLOSED_TEST_STATUSES = ["CLOSED_PASS", "CLOSED_FAST", "CLOSED_SLOW"]
TEST_TYPES = ["FIELD", "BENCH"]
REQUESTED_BY_KINDS = ["CUSTOMER", "UTILITY"]
FIELD_RESULTS = ["PASS", "SUSPECT"]
BENCH_RESULTS = ["PASS", "FAST", "SLOW"]
ACCURACY_METHODS = ["AWWA_WEIGHTED", "SIMPLE_MEAN"]
PROOF_STATUSES = ["SUBMITTED", "VERIFIED", "REJECTED"]
ADJUSTMENT_STATUSES = [
    "DRAFT",
    "PENDING_APPROVAL",
    "APPROVED",
    "POSTED",
    "DENIED",
    "REVERSED",
]
ARRANGEMENT_STATUSES = ["PROPOSED", "ACTIVE", "COMPLETED", "DEFAULTED", "CANCELLED"]
APPEAL_STATUSES = ["FILED", "SCHEDULED", "UPHELD", "REVERSED", "REMANDED"]
APPEAL_DECISIONS = ["UPHOLD", "REVERSE", "REMAND"]
SERVICE_STATUSES = ["ACTIVE", "SHUTOFF_SCHEDULED", "SHUTOFF_HELD", "SHUTOFF_EXECUTED"]
CREDIT_STATUSES = ["CURRENT", "PAST_DUE", "IN_ARRANGEMENT", "ARRANGEMENT_DEFAULTED"]
ENTRY_TYPES = ["CHARGE", "CREDIT", "PAYMENT", "REVERSAL"]
SOURCE_KINDS = [
    "BILL_CHARGE",
    "REBILL_REVERSAL",
    "REBILL_CHARGE",
    "LEAK_ADJUSTMENT_CREDIT",
    "LEAK_ADJUSTMENT_ADMIN_FEE",
    "LEAK_ADJUSTMENT_REVERSAL",
    "METER_TEST_DEPOSIT",
    "METER_TEST_DEPOSIT_REFUND",
    "CUSTOMER_PAYMENT",
    "ARRANGEMENT_DOWN_PAYMENT",
    "ARRANGEMENT_INSTALLMENT",
]

# Ledger entries are append-only and therefore carry no mutable audit fields.
LEDGER_FORBIDDEN_FIELDS = ["updated_at", "version"]
