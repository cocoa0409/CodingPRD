"""Domain thresholds and canonical test data drawn from the PRD's calculations."""

# ── Complaint ratio and risk tier ──────────────────────────────────────────
RISK_TIER_THRESHOLDS = {
    "HIGH": 5.00,
    "ELEVATED": 2.50,
    "MODERATE": 1.00,
}

# ── Composite analysis score ───────────────────────────────────────────────
COMPLAINT_COMPONENT_TIERS = [
    (5.00, 40),
    (2.50, 28),
    (1.00, 16),
]
COMPLAINT_COMPONENT_BASE = 6
FINANCIAL_WEIGHT = 0.30
FINANCIAL_CAP = 30.00
TREND_WEIGHT = 0.20
TREND_CAP = 30.00
LARGE_PREMIUM_THRESHOLD_CENTS = 5_000_000_000
LARGE_PREMIUM_MULTIPLIER = 1.10
STANDARD_MULTIPLIER = 1.00
COMPOSITE_CAP = 100.00

# ── Target selection ───────────────────────────────────────────────────────
MIN_COMPOSITE_SCORE_DEFAULT = 40.00
DEPARTMENT_STATE_CODE = "NV"

# ── Data call completeness ─────────────────────────────────────────────────
LATE_PENALTY_PCT_PER_DAY = 0.50
ACCEPTANCE_COMPLETENESS_PCT = 95.00
DATA_CALL_BUFFER_DAYS = 3

# ── Sampling plan ──────────────────────────────────────────────────────────
AREA_PREFIX = {
    "UNDERWRITING": "UW",
    "RATING": "RT",
    "CLAIMS": "CLM",
    "PRODUCER": "PRD",
}
MIN_SAMPLE_SIZE_ON_SITE = 10
MIN_SAMPLE_SIZE_DESK = 5

# ── Error rates and tolerance ──────────────────────────────────────────────
AREA_TOLERANCE_DEFAULTS = {
    "UNDERWRITING": 7.00,
    "RATING": 5.00,
    "CLAIMS": 3.00,
    "PRODUCER": 10.00,
}
MATERIAL_ESCALATION_PCT = 10.00

# ── Penalty determination ──────────────────────────────────────────────────
PER_UNIT_PENALTY_CENTS = 25_000
TIER1_WIDTH_CENTS = 5_000_000
TIER1_RATE = 0.10
TIER2_WIDTH_CENTS = 20_000_000
TIER2_RATE = 0.06
TIER3_RATE = 0.03
BASE_PER_SUSTAINED_CRITICISM_CENTS = 100_000
CREDIT_TIER_THRESHOLD_CENTS = 25_000_000
LOW_CREDIT_PCT = 0.05
HIGH_CREDIT_PCT = 0.15
STATUTORY_CAP_CENTS = 50_000_000

# ── Rebuttal loop ──────────────────────────────────────────────────────────
MAX_RESPONSE_ROUNDS = 3

# ── Follow-up scheduling ───────────────────────────────────────────────────
FOLLOWUP_MONTHS_EGREGIOUS = 12
FOLLOWUP_MONTHS_MATERIAL = 18
FOLLOWUP_MONTHS_MINOR = 24
FOLLOWUP_WINDOW_DAYS = 60

# ── Pagination ─────────────────────────────────────────────────────────────
DEFAULT_LIMIT = 10
MAX_LIMIT = 100
MIN_LIMIT = 1

# ── The logical clock's value before any client sets it ─────────────────────
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

# ── Canonical test data reused across setups ───────────────────────────────
TEST_DEFAULTS = {
    "INSURER_NAME": "Aurora Mutual Insurance Company",
    "NAIC_CODE": "10001",
    "ANNUAL_PREMIUM_WRITTEN_CENTS": 1_200_000_000,
    "POLICY_COUNT_IN_FORCE": 40_000,
    "CONFIRMED_COMPLAINTS_12MO": 120,
    "FINANCIAL_STRESS_SCORE": 60,
    "CONSUMER_TREND_SCORE": 50,
    "LEAD_STATE_CODE": "NV",
    "FIELDWORK_START_DATE": "2026-09-01",
    "FIELDWORK_END_DATE": "2026-11-30",
    "RESPONSE_DUE_DATE": "2026-09-15",
    "SUBMITTED_BY_CONTACT": "D. Reyes, Compliance Director",
    "STATUTE_CITATION": "NRS 686A.310(1)(e)",
    "REFERENCE_PERIOD_START": "2025-07-01",
    "REFERENCE_PERIOD_END": "2026-06-30",
    "NARRATIVE": (
        "The carrier will retrain claims adjusters, re-run the prompt-pay audit "
        "and remediate affected files."
    ),
    "PUBLIC_SUMMARY": (
        "The department completed its market conduct examination of the carrier "
        "and publishes this summary of findings."
    ),
    "ABORT_REASON": (
        "The carrier entered voluntary run-off and the department suspended the "
        "examination."
    ),
}

# The standard three-state multistate roster: NV leads on policy count, UT has
# no examiner resources and is therefore ineligible for the lead election.
STANDARD_PARTICIPATING_STATES = [
    {"state_code": "NV", "policy_count_in_state": 40_000, "has_examiner_resources": True},
    {"state_code": "AZ", "policy_count_in_state": 25_000, "has_examiner_resources": True},
    {"state_code": "UT", "policy_count_in_state": 9_000, "has_examiner_resources": False},
]
