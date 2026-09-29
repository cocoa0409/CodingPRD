"""Constants transcribed from the PRD of the Online Program Management Partnership API.

Every value here appears verbatim in the PRD; nothing is invented. Section
references in comments point at the PRD section that fixes the value.
"""

# --- Roles (PRD 2.1) -------------------------------------------------------
ROLE_PLATFORM_ADMIN = "PlatformAdmin"
ROLE_UNIVERSITY_PROVOST = "UniversityProvost"
ROLE_UNIVERSITY_BURSAR = "UniversityBursar"
ROLE_FACULTY_CHAIR = "FacultyChair"
ROLE_COMPLIANCE_AUDITOR = "ComplianceAuditor"
ROLE_PARTNER_ACCOUNT_LEAD = "PartnerAccountLead"

ALL_ROLES = (
    ROLE_PLATFORM_ADMIN,
    ROLE_UNIVERSITY_PROVOST,
    ROLE_UNIVERSITY_BURSAR,
    ROLE_FACULTY_CHAIR,
    ROLE_COMPLIANCE_AUDITOR,
    ROLE_PARTNER_ACCOUNT_LEAD,
)

# --- Logical clock (PRD 2.4) ----------------------------------------------
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

# --- Pagination (PRD 2.3) -------------------------------------------------
DEFAULT_PAGE_LIMIT = 10
MIN_PAGE_LIMIT = 1
MAX_PAGE_LIMIT = 100
DEFAULT_PAGE_OFFSET = 0

# --- Contract terms (PRD 3.1) ---------------------------------------------
MIN_TERM_MONTHS = 12
MAX_TERM_MONTHS = 120

# Standard marginal revenue-share ladder applied when revenue_share_tiers is omitted.
DEFAULT_REVENUE_SHARE_TIERS = (
    {"through_cents": 25000000, "partner_rate": 0.575},
    {"through_cents": 75000000, "partner_rate": 0.485},
    {"through_cents": None, "partner_rate": 0.395},
)

# Standard withdrawal refund schedule applied when refund_schedule is omitted.
DEFAULT_REFUND_SCHEDULE = (
    {"through_day": 7, "refund_pct": 1.00},
    {"through_day": 21, "refund_pct": 0.50},
    {"through_day": 35, "refund_pct": 0.25},
    {"through_day": None, "refund_pct": 0.00},
)

DEFAULT_FEE_SCHEDULE_MONTHLY_CENTS = 0

# --- Demand score (PRD 3.2) ----------------------------------------------
DEMAND_WEIGHT_ENROLLMENT = 40
DEMAND_WEIGHT_COMPETITION = 25
DEMAND_WEIGHT_WAGE = 20
DEMAND_WEIGHT_EMPLOYER = 15

PROJECTION_CEILING = 400
COMPETITOR_CEILING = 30
WAGE_PREMIUM_CEILING = 20
EMPLOYER_CEILING = 15

MODALITY_FACTORS = {
    "ASYNCHRONOUS": 1.00,
    "SYNCHRONOUS": 0.92,
    "HYBRID": 0.96,
}

CONFIRMED_INQUIRY_YIELD = 0.10
SUBMIT_MIN_SCORE = 45.00
APPROVAL_MIN_SCORE = 62.00

# Default required_service_domains when the array is omitted (PRD 3.2).
DEFAULT_REQUIRED_SERVICE_DOMAINS = (
    "MARKETING",
    "LEAD_GENERATION",
    "ENROLLMENT_COUNSELING",
    "COURSE_DESIGN",
    "STUDENT_ADVISING",
    "ACCESSIBILITY_ACCOMMODATIONS",
)

# --- Service scope (PRD 2.9 / 3.3) ---------------------------------------
NON_DELEGABLE_SERVICE_DOMAINS = (
    "COURSE_DESIGN",
    "FACULTY_TRAINING",
    "ACCESSIBILITY_ACCOMMODATIONS",
)
DEFAULT_SLA_RESPONSE_HOURS = 24
DEFAULT_COST_BEARER = "PARTNER"

# --- Compensation compliance (PRD 3.5) -----------------------------------
VARIABLE_COMP_ENVELOPE_PCT = 0.20
MIN_RATED_PIPELINE = 4
MEETS_STANDARD_MIN_RATE = 0.2500
WATCH_MIN_RATE = 0.1500
SLA_BREACH_MAX_RATIO = 0.3000

# --- Withdrawal clawback (PRD 3.7) ---------------------------------------
CLAWBACK_WINDOW_DAYS = 45
CLAWBACK_SUSPENSION_TRIGGER_CENTS = 50000

# --- Settlement waterfall (PRD 3.8) -------------------------------------
RECOUPMENT_CAP_PCT = 0.15
HOLDBACK_TRIGGER_CENTS = 10000000
HOLDBACK_HIGH_PCT = 0.10
HOLDBACK_LOW_PCT = 0.05

# --- Teach-out (PRD 3.9) -------------------------------------------------
TEACH_OUT_COST_PER_CREDIT_CENTS = 18000
PARTNER_OBLIGATION_CAP_PCT = 0.40
TEACH_OUT_NOTICE_MIN_DAYS = 90
ASSET_TRANSFER_SCOPE_FACTORS = {
    "NONE": 0.0,
    "COURSE_CONTENT_ONLY": 0.50,
    "COURSE_CONTENT_AND_LEAD_DATA": 0.75,
    "FULL_PLATFORM": 1.00,
}

# --- Statement status groupings (PRD 3.1 / 3.8 / 3.9) -------------------
OPEN_STATEMENT_STATUSES = (
    "CALCULATED",
    "UNIVERSITY_APPROVED",
    "DISPUTED",
    "RESOLVED_ADJUSTED",
    "STALE",
)
