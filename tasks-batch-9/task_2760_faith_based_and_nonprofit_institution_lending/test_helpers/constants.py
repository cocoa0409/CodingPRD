"""
Domain constants for the Faith-Based and Nonprofit Institution Lending API.

Every value here is transcribed from the PRD under test. Nothing is invented:
where the PRD states a percentage, a tier table, a floor or a cap, the literal
appears once here and is referenced from the test suite.
"""

# ─── Logical clock (PRD §2.5) ──────────────────────────────────────────────
# "The clock's value at startup is exactly `2026-08-01T00:00:00Z`"
CLOCK_STARTUP_UTC = "2026-08-01T00:00:00Z"

# ─── Pagination (PRD §2.3) ────────────────────────────────────────────────
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# Collections that return the newest record first (created_at DESC).
CREATED_AT_DESC_COLLECTIONS = (
    "institutions",
    "governance-authorizations",
    "pledge-campaigns",
    "loan-applications",
    "loans",
)

# ─── Roles (PRD §2.1) ─────────────────────────────────────────────────────
ROLE_PLATFORM_ADMIN = "PlatformAdmin"
ROLE_INSTITUTION_REPRESENTATIVE = "InstitutionRepresentative"
ROLE_GOVERNANCE_OFFICER = "GovernanceOfficer"
ROLE_CREDIT_ANALYST = "CreditAnalyst"
ROLE_CREDIT_COMMITTEE_MEMBER = "CreditCommitteeMember"
ROLE_LOAN_SERVICER = "LoanServicer"

ALL_ROLES = (
    ROLE_PLATFORM_ADMIN,
    ROLE_INSTITUTION_REPRESENTATIVE,
    ROLE_GOVERNANCE_OFFICER,
    ROLE_CREDIT_ANALYST,
    ROLE_CREDIT_COMMITTEE_MEMBER,
    ROLE_LOAN_SERVICER,
)

# ─── Enumerations (PRD §3) ────────────────────────────────────────────────
INSTITUTION_TYPES = ("CONGREGATION", "SCHOOL", "DENOMINATIONAL_AGENCY", "NONPROFIT_MINISTRY")
GIVING_PERIOD_SOURCES = ("AUDITED", "INTERNAL")
GIVING_BASES = ("AUDITED_ONLY", "BLENDED")
AUTHORIZATION_STATUSES = ("DRAFT", "SUBMITTED", "BOARD_VERIFIED", "AUTHORIZED", "DENOM_REJECTED")
DENOMINATIONAL_DECISIONS = ("APPROVE", "REJECT")
CAMPAIGN_STATUSES = ("OPEN", "UNDERPERFORMING", "CLOSED")
CAMPAIGN_VALUATION_BASES = ("LENDER_CONSERVATIVE", "SPONSOR_OPTIMISTIC")
DONOR_TIERS = ("LEAD", "MAJOR", "GENERAL")
PLEDGE_STATUSES = ("ACTIVE", "FULFILLED", "LAPSED")
INSTALLMENT_OUTCOMES = ("PAID", "MISSED")
ASSET_TYPES = (
    "SANCTUARY",
    "EDUCATION_WING",
    "PARSONAGE",
    "LAND",
    "FELLOWSHIP_HALL",
    "DONOR_RESTRICTED_ENDOWMENT",
)
APPLICATION_PURPOSES = (
    "SANCTUARY_CONSTRUCTION",
    "SCHOOL_CONSTRUCTION",
    "REFINANCE",
    "PLEDGE_ADVANCE",
)
APPLICATION_STATUSES = (
    "DRAFT",
    "UNDERWRITING",
    "COMMITTEE_REVIEW",
    "APPROVED",
    "DECLINED",
    "REVISION_REQUESTED",
    "FUNDED",
)
COMMITTEE_DECISIONS = ("APPROVE", "DECLINE", "REQUEST_REVISION")
TERM_MONTHS_ALLOWED = (120, 180, 240)
SERVICING_STATUSES = ("PENDING_FIRST_DRAW", "CONSTRUCTION_DRAW", "AMORTIZING", "PAID_OFF")
RISK_POSTURES = ("OPEN", "WATCH", "RESTRICTED", "WORKOUT_GATED")
PROJECT_PHASES = (
    "SITE_WORK",
    "FOUNDATION",
    "SHELL",
    "SANCTUARY_FITOUT",
    "SCHOOL_FITOUT",
    "FINAL",
)
DRAW_STATUSES = ("SUBMITTED", "APPROVED", "DISBURSED", "REJECTED", "VOIDED", "SUSPENDED")
COVENANT_TYPES = ("DSCR_UNRESTRICTED_GIVING", "MEMBERSHIP_TREND", "PLEDGE_COLLECTION_RATE")
TEST_FREQUENCIES = ("QUARTERLY", "ANNUAL")
COVENANT_STATUSES = ("COMPLIANT", "BREACH_PENDING_CURE", "BREACHED", "WAIVED")
TEST_RESULTS = ("PASS", "FAIL")
WORKOUT_OPTIONS = (
    "PAYMENT_DEFERRAL",
    "TERM_EXTENSION",
    "MISSION_IMPACT_FORBEARANCE",
    "PARTIAL_FORGIVENESS",
)
WORKOUT_STATUSES = ("PROPOSED", "APPROVED", "SUPERSEDED")
BINDING_CAPS = ("DEBT_SERVICE", "COLLATERAL", "BYLAWS_CAP", "AUTHORIZED_AMOUNT", "PLEDGE_ADVANCE_LTV")

# ─── Giving analysis (PRD §3.1, §3.5) ─────────────────────────────────────
MIN_GIVING_PERIODS = 4          # "at least four giving periods on file"
GIVING_WINDOW_SIZE = 4          # "the window is then the first four candidates"
INTERNAL_HAIRCUT_PCT = 0.15     # "the 15 percent internal-statement haircut"
INTERNAL_CONTRIBUTION_FACTOR = 0.85

# ─── Sizing caps (PRD §3.5) ───────────────────────────────────────────────
MIN_DSCR = 1.2000               # "the minimum debt-service coverage ratio of 1.2000"
TERM_FACTOR_BY_TERM_MONTHS = {120: 5.5, 180: 7.0, 240: 8.5}
PLEDGE_ADVANCE_LTV = 0.60       # "multiplied by 60 percent"

# ─── Campaign attrition and valuation (PRD §3.3) ──────────────────────────
ATTRITION_PCT_BY_TIER = {"LEAD": 0.05, "MAJOR": 0.12, "GENERAL": 0.22}
MISSED_PAYMENT_PENALTY_PCT = 0.15   # "a further 15 percentage points"
MISSED_PAYMENT_PENALTY_THRESHOLD = 2  # "missed two or more installments"
ATTRITION_RATE_CEILING = 0.60       # "capped at 60 percent"
AUTO_LAPSE_MISSED_COUNT = 3         # "brings `missed_payments_count` to exactly 3"
AUTO_LAPSE_REASON = "AUTO_THREE_MISSED_INSTALLMENTS"
CAMPAIGN_MATURITY_PCT = 0.90        # "the goal multiplied by 90 percent"
CAMPAIGN_UNDERPERFORM_PCT = 0.80    # "the goal multiplied by 80 percent"
CAMPAIGN_UNDERPERFORM_REVISION_REASON = "PLEDGE_CAMPAIGN_UNDERPERFORMING"
BPS_WHOLE = 10000                   # "10000 basis points is the whole"

# ─── Collateral valuation (PRD §3.4) ──────────────────────────────────────
ADVANCE_RATE_BY_ALT_USE_SCORE = {1: 0.40, 2: 0.50, 3: 0.60, 4: 0.70, 5: 0.75}
ADVANCE_RATE_CAP_BY_ASSET_TYPE = {
    "SANCTUARY": 0.55,
    "EDUCATION_WING": 0.65,
    "PARSONAGE": 0.70,
    "LAND": 0.50,
    "FELLOWSHIP_HALL": 0.60,
    "DONOR_RESTRICTED_ENDOWMENT": 0.00,
}
LIEN_FACTOR_BY_POSITION = {1: 1.00, 2: 0.60, 3: 0.00}
APPRAISAL_SEASONING_DAYS = 365      # "strictly greater than 365"
SEASONED_APPRAISAL_FACTOR = 0.90    # "multiplied by 90 percent"
APPRAISAL_STALE_DAYS = 730          # "at most 730"
LIEN_RELEASE_BUFFER_DAYS = 30       # "a 30-day tail after every prior occupation"

# ─── Disbursement waterfall (PRD §3.7) ────────────────────────────────────
RETAINAGE_PCT_TIER_LOW = 0.10       # completion below 0.5000
RETAINAGE_PCT_TIER_MID = 0.05       # 0.5000 up to but not including 0.9000
RETAINAGE_PCT_TIER_HIGH = 0.00      # 0.9000 and above
RETAINAGE_TIER_MID_FLOOR = 0.5000
RETAINAGE_TIER_HIGH_FLOOR = 0.9000
INSPECTION_FEE_CENTS = 45000        # "45000 cents — a flat 450 dollars per disbursement"

# ─── Mission impact score (PRD §3.9) ──────────────────────────────────────
COMMUNITY_POINTS_PER_PROGRAM = 20
COMMUNITY_POINTS_CAP = 100
TREND_POINTS_FLAT_OR_UP = 100
TREND_POINTS_MILD_DECLINE = 70      # negative but no worse than a 5 percent decline
TREND_POINTS_MODERATE_DECLINE = 40  # worse than that but no worse than 15 percent
TREND_POINTS_STEEP_DECLINE = 10
MISSION_WEIGHT_MEMBERSHIP = 0.35
MISSION_WEIGHT_GIVING = 0.25
MISSION_WEIGHT_COMMUNITY = 0.20
MISSION_WEIGHT_DENOMINATIONAL = 0.20
DENOMINATIONAL_POINTS_WITH_LETTER = 100
DENOMINATIONAL_POINTS_WITHOUT_LETTER = 0
PARTIAL_FORGIVENESS_MIN_SCORE = 92.00
FORBEARANCE_MIN_SCORE = 50.00
DEFERRAL_MONTHS_MIN = 1
DEFERRAL_MONTHS_MAX = 24
EXTENSION_MONTHS_MIN = 1
EXTENSION_MONTHS_MAX = 120
