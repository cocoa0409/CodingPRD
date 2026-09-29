"""Domain thresholds and pinned numeric constants stated in the PRD."""

# --- Logical clock (PRD §2.5) ---
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

# --- Channel no-show probation (PRD §3.1) ---
NO_SHOW_MIN_SAMPLE = 4
NO_SHOW_SUSPEND_THRESHOLD = 0.5000
CHANNEL_SUSPENDED_CANCEL_REASON = "CHANNEL_SUSPENDED"

# --- Tour qualification scoring (PRD §3.3) ---
NO_SHOW_PENALTY_WEIGHT = 30
QUALIFICATION_SCORE_CAP = 100
INCOME_TIER_POINTS = [
    (15_000_000, 45),
    (10_000_000, 35),
    (7_500_000, 25),
    (5_000_000, 15),
]
AGE_POINTS = 25
MARITAL_POINTS = 20
OWNER_POINTS = 25
AFFINITY_POINTS = 20
AFFINITY_CHANNEL_CODES = ("IN_HOUSE_REFERRAL", "OWNER_UPGRADE")

# --- Booking (PRD §3.4) ---
MIN_BOOKING_LEAD_MINUTES = 60
RESCHEDULE_LIMIT = 2
OCCUPYING_BOOKING_STATUSES = (
    "SCHEDULED",
    "RESCHEDULE_PENDING",
    "CHECKED_IN",
    "TOURED",
)
GIFT_ACCRUING_BOOKING_STATUSES = ("CHECKED_IN", "TOURED")

# --- Rotation / calendar exclusivity (PRD §3.5) ---
REP_RESET_MINUTES = 15

# --- Presentation compliance (PRD §3.6) ---
REQUIRED_DISCLOSURE_CODES = (
    "RESCISSION_RIGHTS",
    "PUBLIC_OFFERING_STATEMENT_DELIVERY",
    "NOT_AN_INVESTMENT",
)
REQUIRED_DISCLOSURE_COUNT = 3
DISCLOSURE_GAP_WEIGHT = 10
SEVERITY_PENALTY_POINTS = {"MINOR": 5, "MAJOR": 15, "EGREGIOUS": 40}
COMPLIANCE_CLEAR_FLOOR = 70
COMPLIANCE_STRIKE_SUSPEND_THRESHOLD = 2

# --- Trade-in equity credit (PRD §3.7) ---
EQUITY_RECOGNITION_RATE = 0.55
ANNUAL_DEPRECIATION_RATE = 0.075
LOYALTY_RATE = 0.025
LOYALTY_YEARS_CAP = 10
TRANSFER_FEE_CENTS = 49900
SECONDS_PER_YEAR = 31_536_000

# --- Contract financials (PRD §3.7) ---
DOWN_PAYMENT_TIERS = [(5_000_000, 0.12), (2_000_000, 0.10)]
DOWN_PAYMENT_BASE_RATE = 0.08
DOC_STAMP_RATE = 0.0035
CLOSING_FLAT_FEE_CENTS = 129900

# --- Jurisdictional rescission rules (PRD §2.7) ---
STATE_RESCISSION_RULES = {
    "FL": {
        "statutory_rescission_days": 10,
        "anchor_mode": "LATER_OF_EXECUTION_OR_POS",
        "business_day_roll": True,
        "refund_policy": "STATUTORY_FULL",
    },
    "NV": {
        "statutory_rescission_days": 5,
        "anchor_mode": "EXECUTION",
        "business_day_roll": False,
        "refund_policy": "STATUTORY_FULL",
    },
    "CA": {
        "statutory_rescission_days": 7,
        "anchor_mode": "LATER_OF_EXECUTION_OR_POS",
        "business_day_roll": True,
        "refund_policy": "STATUTORY_FULL",
    },
    "TX": {
        "statutory_rescission_days": 6,
        "anchor_mode": "EXECUTION",
        "business_day_roll": False,
        "refund_policy": "CONTRACTUAL_NET_OF_GIFT",
    },
    "HI": {
        "statutory_rescission_days": 7,
        "anchor_mode": "POS_DELIVERY",
        "business_day_roll": True,
        "refund_policy": "CONTRACTUAL_NET_OF_GIFT",
    },
}

FEDERAL_HOLIDAYS = (
    "2026-07-03",
    "2026-09-07",
    "2026-11-26",
    "2026-12-25",
    "2027-01-01",
    "2028-07-04",
    "2028-09-04",
    "2028-11-23",
    "2028-12-25",
    "2029-01-01",
    "2029-07-04",
    "2029-09-03",
    "2029-11-22",
    "2029-12-25",
)

# --- POS delivery window (PRD §3.7) ---
POS_WINDOW_DAYS_BEFORE = 30
POS_WINDOW_DAYS_AFTER = 3

# --- Refund settlement (PRD §3.9) ---
GIFT_RECAPTURE_CAP_RATE = 0.05
DOC_PREP_FEE_CENTS = 19900

# --- Financing underwriting (PRD §3.8) ---
FICO_TIERS = [(740, 1099, 0.95), (680, 1399, 0.90), (620, 1699, 0.80)]
MIN_UNDERWRITABLE_FICO = 620
LEGAL_TERM_MONTHS = (60, 120, 180)

# --- Representative rescission analysis (PRD §3.9) ---
CANCELLATION_WINDOW_DAYS = 90
CANCELLATION_MIN_SAMPLE = 2
CANCELLATION_RATE_THRESHOLD = 0.5000

# --- Retraining (PRD §3.9) ---
AUTO_RETRAINING_MODULE_COUNT = 4
RETRAINING_CYCLE_LIMIT = 3

# --- Pagination (PRD §2.3) ---
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# --- Values reused verbatim across the suite's scenarios ---
UNKNOWN_UUID = "00000000-0000-4000-8000-000000000001"
