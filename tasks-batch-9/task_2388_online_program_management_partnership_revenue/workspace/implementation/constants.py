"""Enumerations, defaults and calculation constants read from the scaffold."""

ROLES = (
    "PlatformAdmin",
    "UniversityProvost",
    "UniversityBursar",
    "FacultyChair",
    "ComplianceAuditor",
    "PartnerAccountLead",
)

ALL_READ_ROLES = list(ROLES)

CONTRACT_STRUCTURES = ("REVENUE_SHARE", "FEE_FOR_SERVICE")
RECOGNITION_METHODS = ("PERIOD_STRAIGHT_LINE", "MILESTONE_CHRONOLOGICAL")
PARTNERSHIP_STATUSES = ("DRAFT", "UNDER_REVIEW", "EXECUTED", "WIND_DOWN", "CLOSED_OUT")

DELIVERY_MODALITIES = ("ASYNCHRONOUS", "SYNCHRONOUS", "HYBRID")
CREDENTIAL_LEVELS = ("CERTIFICATE", "BACHELORS", "MASTERS", "DOCTORATE")
PROGRAM_STATUSES = ("DRAFT", "SUBMITTED", "REVISION_REQUESTED", "APPROVED", "LAUNCHED",
                    "SUSPENDED", "TEACH_OUT", "CLOSED", "REJECTED")

CONTENT_OWNERS = ("UNIVERSITY", "PARTNER", "JOINT")
DESIGN_STATUSES = ("NOT_STARTED", "IN_DESIGN", "FACULTY_REVIEW", "APPROVED",
                   "DESIGN_SUSPENDED", "RETIRED")

SERVICE_DOMAINS = ("MARKETING", "LEAD_GENERATION", "ENROLLMENT_COUNSELING", "COURSE_DESIGN",
                   "FACULTY_TRAINING", "TECH_PLATFORM", "STUDENT_ADVISING", "TUTORING",
                   "RETENTION_OUTREACH", "CAREER_SERVICES", "ACCESSIBILITY_ACCOMMODATIONS",
                   "FIELD_PLACEMENT")
NON_DELEGABLE_DOMAINS = ("COURSE_DESIGN", "FACULTY_TRAINING", "ACCESSIBILITY_ACCOMMODATIONS")
PARTIES = ("UNIVERSITY", "PARTNER")

DEFAULT_REQUIRED_SERVICE_DOMAINS = ["MARKETING", "LEAD_GENERATION", "ENROLLMENT_COUNSELING",
                                    "COURSE_DESIGN", "STUDENT_ADVISING",
                                    "ACCESSIBILITY_ACCOMMODATIONS"]

# comp_plan_type accepts two request-only members so the prohibited shapes are
# expressible and therefore rejectable; neither is ever persisted.
COMP_PLAN_TYPES_PERSISTED = ("NONE_ON_FILE", "FIXED_SALARY", "SALARY_PLUS_QUALITATIVE",
                             "GRADUATION_MILESTONE")
COMP_PLAN_TYPES_REQUEST = COMP_PLAN_TYPES_PERSISTED + ("PER_ENROLLMENT_COMMISSION",
                                                       "PER_APPLICATION_BOUNTY")
VARIABLE_BASES_PERSISTED = ("NONE", "QUALITATIVE_MULTI_FACTOR", "GRADUATION_COUNT")
VARIABLE_BASES_REQUEST = VARIABLE_BASES_PERSISTED + ("ENROLLMENT_COUNT", "APPLICATION_COUNT")

PERFORMANCE_STATUSES = ("NOT_RATED", "MEETS_STANDARD", "WATCH", "PROBATION",
                        "INACTIVE_PENDING_REVIEW")
INCENTIVE_ELIGIBILITIES = ("PENDING_COMPLIANCE_REVIEW", "ELIGIBLE", "SUSPENDED",
                           "PROHIBITED_PLAN_ON_FILE")

LEAD_SOURCE_CHANNELS = ("PAID_SEARCH", "PAID_SOCIAL", "ORGANIC", "EMPLOYER_REFERRAL",
                        "LIST_PURCHASE")
LEAD_STATUSES = ("NEW", "CONTACTED", "APPLIED", "ENROLLED", "DISQUALIFIED")
DISQUALIFICATION_REASONS = ("NOT_QUALIFIED", "UNREACHABLE", "WITHDREW_INTEREST",
                            "PROGRAM_TEACH_OUT")

ENROLLMENT_STATUSES = ("ENROLLED", "ACTIVE", "COMPLETED", "WITHDRAWN")
TUITION_ENTRY_TYPES = ("PAYMENT", "REFUND")
MARKETING_ENTRY_TYPES = ("SPEND", "CREDIT_MEMO")
MARKETING_CHANNELS = ("PAID_SEARCH", "PAID_SOCIAL", "DISPLAY", "EVENTS", "LIST_PURCHASE")

STATEMENT_STATUSES = ("CALCULATED", "UNIVERSITY_APPROVED", "DISPUTED", "RESOLVED_ADJUSTED",
                      "STALE", "REMITTED")
OPEN_STATEMENT_STATUSES = ("CALCULATED", "UNIVERSITY_APPROVED", "DISPUTED",
                           "RESOLVED_ADJUSTED", "STALE")

ASSET_TRANSFER_SCOPES = ("NONE", "COURSE_CONTENT_ONLY", "COURSE_CONTENT_AND_LEAD_DATA",
                         "FULL_PLATFORM")
TEACH_OUT_PLAN_STATUSES = ("DRAFT", "CERTIFIED", "SUPERSEDED")

DEFAULT_REVENUE_SHARE_TIERS = [
    {"through_cents": 25000000, "partner_rate": 0.575},
    {"through_cents": 75000000, "partner_rate": 0.485},
    {"through_cents": None, "partner_rate": 0.395},
]

DEFAULT_REFUND_SCHEDULE = [
    {"through_day": 7, "refund_pct": 1.00},
    {"through_day": 21, "refund_pct": 0.50},
    {"through_day": 35, "refund_pct": 0.25},
    {"through_day": None, "refund_pct": 0.00},
]

# program_demand_score
W_ENROLLMENT = 40
W_COMPETITION = 25
W_WAGE = 20
W_EMPLOYER = 15
PROJECTION_CAP = 400
COMPETITOR_CAP = 30
WAGE_PREMIUM_CAP = 20
EMPLOYER_CAP = 15
MODALITY_FACTOR = {"ASYNCHRONOUS": "1.00", "SYNCHRONOUS": "0.92", "HYBRID": "0.96"}
CONFIRMED_INQUIRY_YIELD = "0.10"
SUBMIT_MIN_SCORE = "45.00"
APPROVAL_MIN_SCORE = "62.00"

# net_remittance_payable
RECOUP_CAP_PCT = "0.15"
HOLDBACK_TRIGGER_CENTS = 10000000
HOLDBACK_HIGH_PCT = "0.10"
HOLDBACK_LOW_PCT = "0.05"

# withdrawal_refund_and_clawback
CLAWBACK_WINDOW_DAYS = 45
CLAWBACK_SUSPENSION_TRIGGER_CENTS = 50000

# counselor_conversion_performance
MIN_RATED_PIPELINE = 4
MEETS_THRESHOLD = "0.2500"
WATCH_THRESHOLD = "0.1500"
SLA_BREACH_MAX_RATIO = "0.3000"

# teach_out_obligation_liability
TEACH_OUT_COST_PER_CREDIT_CENTS = 18000
PARTNER_OBLIGATION_CAP_PCT = "0.40"
TEACH_OUT_NOTICE_MIN_DAYS = 90
ASSET_TRANSFER_SCOPE_FACTOR = {
    "NONE": "0.00",
    "COURSE_CONTENT_ONLY": "0.50",
    "COURSE_CONTENT_AND_LEAD_DATA": "0.75",
    "FULL_PLATFORM": "1.00",
}

# action -> role maps (PRD 2.5 item 5)
CONTRACT_ACTION_ROLES = {
    "SUBMIT_FOR_REVIEW": ("PartnerAccountLead",),
    "REQUEST_CHANGES": ("UniversityProvost",),
    "EXECUTE": ("UniversityProvost",),
    "WIND_DOWN": ("UniversityProvost",),
    "CLOSE_OUT": ("UniversityProvost",),
}

LIFECYCLE_ACTION_ROLES = {
    "SUBMIT": ("PartnerAccountLead",),
    "LAUNCH": ("PartnerAccountLead",),
    "REQUEST_REVISION": ("UniversityProvost",),
    "APPROVE": ("UniversityProvost",),
    "REJECT": ("UniversityProvost",),
    "SUSPEND": ("UniversityProvost",),
    "RESUME": ("UniversityProvost",),
    "BEGIN_TEACH_OUT": ("UniversityProvost",),
    "CLOSE": ("UniversityProvost",),
}

DESIGN_ACTION_ROLES = {
    "START_DESIGN": ("PartnerAccountLead",),
    "SUBMIT_FOR_FACULTY_REVIEW": ("PartnerAccountLead",),
    "REQUEST_REVISION": ("FacultyChair",),
    "APPROVE": ("FacultyChair",),
    "RETIRE": ("FacultyChair",),
}

STATEMENT_ACTION_ROLES = {
    "APPROVE": ("UniversityProvost",),
    "DISPUTE": ("PartnerAccountLead",),
    "RESOLVE": ("UniversityBursar",),
    "REMIT": ("UniversityBursar",),
    "RECALCULATE": ("UniversityBursar",),
}

ACADEMIC_ACTION_ROLES = {
    "WITHDRAW": ("UniversityBursar",),
    "RECORD_PROGRESS": ("UniversityProvost",),
    "COMPLETE": ("UniversityProvost",),
}
