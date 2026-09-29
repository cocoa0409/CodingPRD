"""Domain thresholds and pinned numeric constants named by the PRD."""

# --- Logical clock -----------------------------------------------------------
# "Before any clock write, the logical clock reads exactly 2026-08-01T00:00:00Z".
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

# --- Shift and payroll capacity ceilings ------------------------------------
MAX_SHIFT_HOURS = 16.00
MAX_REPORTED_HOURS_PER_WORKER_DAY = 20.00
PAYROLL_HOURS_PER_DAY = 24.00

# --- Census reconciliation ---------------------------------------------------
CENSUS_VARIANCE_TOLERANCE = 0.0500

# --- Hours per resident day --------------------------------------------------
MAX_PLAUSIBLE_HPRD = 12.0000

# --- Audit readiness ---------------------------------------------------------
AUDIT_RISK_FLOOR = 70.00
AUDIT_SAMPLE_SIZE = 5
SUPPORT_RATIO_WEIGHT = 0.50
VENDOR_ATTESTATION_RATIO_WEIGHT = 0.30
CENSUS_RECONCILED_RATIO_WEIGHT = 0.20

# --- Star assignment ---------------------------------------------------------
TOTAL_NURSE_HPRD_TIERS = {5: 3.6000, 4: 3.0000, 3: 2.4000, 2: 1.8000}
RN_HPRD_TIERS = {5: 0.7500, 4: 0.5500, 3: 0.3500, 2: 0.2000}
WEEKEND_HPRD_FLOOR = 2.4000
ZERO_RN_DAY_OVERRIDE_COUNT = 4

# --- Amendment surcharge -----------------------------------------------------
BASE_AMENDMENT_FEE_CENTS = 25000
AMENDMENT_ESCALATION_STEP_CENTS = 2500
SURCHARGE_CAP_CENTS = 50000
SECONDS_PER_LATE_DAY = 86400
LATE_RATE_TIERS = [
    (27500, 0.0300),
    (25000, 0.0200),
    (1, 0.0100),
]
LATE_RATE_WHEN_FREE = 0.0000

# --- Appeals -----------------------------------------------------------------
APPEAL_WINDOW_DAYS = 30

# --- Pagination --------------------------------------------------------------
DEFAULT_PAGE_LIMIT = 10
MIN_PAGE_LIMIT = 1
MAX_PAGE_LIMIT = 100

# --- Reference data used by every fixture chain -----------------------------
TEST_DEFAULTS = {
    "FACILITY_CCN": "675001",
    "FACILITY_NAME": "Cedar Grove Care Center",
    "FACILITY_STATE_CODE": "TX",
    "FACILITY_BED_COUNT": 120,
    "SECOND_FACILITY_CCN": "675002",
    "SECOND_FACILITY_NAME": "Willow Bend Nursing",
    "SECOND_FACILITY_BED_COUNT": 90,
    "PERIOD_CODE": "2026Q2",
    "PERIOD_START": "2026-04-01",
    "PERIOD_END": "2026-04-30",
    "PERIOD_DEADLINE": "2026-08-14T23:59:59Z",
    "PERIOD_CORRECTION_END": "2026-12-31T23:59:59Z",
    "SECOND_PERIOD_CODE": "2026Q3",
    "SECOND_PERIOD_START": "2026-07-01",
    "SECOND_PERIOD_END": "2026-07-31",
    "SECOND_PERIOD_DEADLINE": "2026-11-14T23:59:59Z",
    "SECOND_PERIOD_CORRECTION_END": "2027-03-31T23:59:59Z",
    "HIRE_DATE": "2026-01-01",
    "VENDOR_NAME": "Northgate Agency Staffing",
    "VENDOR_TAX_ID": "74-2210099",
    "VENDOR_CONTACT": "ops@northgate.example",
    "VENDOR_ATTESTED_BY": "Northgate Ops Lead",
}

# Opaque operator identities. The PRD records these where a transition writes
# them but never compares them to any entity id.
PLATFORM_ADMIN_USER_ID = "admin-01"
VERIFYING_AUDITOR_USER_ID = "auditor-verify-01"
ACCEPTING_AUDITOR_USER_ID = "auditor-accept-01"
READING_AUDITOR_USER_ID = "auditor-read-01"
CASE_AUDITOR_USER_ID = "auditor-case-01"
PUBLISHER_USER_ID = "publisher-01"
REVIEWER_USER_ID = "reviewer-01"
SYSTEM_USER_ID = "SYSTEM"
