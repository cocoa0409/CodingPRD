"""Enumerations, tunables and standing literals declared by the PRD.

Nothing here is invented: every enum member list, every tunable value and every
role name is copied from the PRD / scaffold entity declarations so that tests
never hard-code a bare string that could drift.
"""

# ---------------------------------------------------------------------------
# Roles (PRD section 2 actor list)
# ---------------------------------------------------------------------------
ROLE_PROGRAM_DIRECTOR = "ProgramDirector"
ROLE_INTAKE_SCREENER = "IntakeScreener"
ROLE_SUPERVISING_ATTORNEY = "SupervisingAttorney"
ROLE_CASE_REPRESENTATIVE = "CaseRepresentative"
ROLE_GRANT_ANALYST = "GrantAnalyst"
ROLE_CLIENT_PORTAL_USER = "ClientPortalUser"

ALL_ROLES = (
    ROLE_PROGRAM_DIRECTOR,
    ROLE_INTAKE_SCREENER,
    ROLE_SUPERVISING_ATTORNEY,
    ROLE_CASE_REPRESENTATIVE,
    ROLE_GRANT_ANALYST,
    ROLE_CLIENT_PORTAL_USER,
)

# Roles whose identity is a Representative.id
ENTITY_BACKED_REP_ROLES = (
    ROLE_INTAKE_SCREENER,
    ROLE_SUPERVISING_ATTORNEY,
    ROLE_CASE_REPRESENTATIVE,
)

# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------
CONSENT_SCOPES = ("NONE", "PROGRAM_ONLY", "FUNDER_AGGREGATE", "FUNDER_IDENTIFIED")
CLIENT_STATUSES = ("ACTIVE", "CLOSED")

# ---------------------------------------------------------------------------
# ProgramCapacityCycle
# ---------------------------------------------------------------------------
CAPACITY_POSTURES = ("OPEN", "RESTRICTED", "FROZEN")

# ---------------------------------------------------------------------------
# DetentionFacility
# ---------------------------------------------------------------------------
FACILITY_STATUSES = ("OPEN", "RESTRICTED_ACCESS", "CLOSED")
DEFAULT_VISIT_LEAD_TIME_HOURS = 48
DEFAULT_EXPEDITED_FILING_DAYS = 21

# ---------------------------------------------------------------------------
# OrganizationRecognition
# ---------------------------------------------------------------------------
FORUMS = ("USCIS", "EOIR_IMMIGRATION_COURT", "BIA", "ASYLUM_OFFICE")
ALL_FORUMS_SORTED = ("ASYLUM_OFFICE", "BIA", "EOIR_IMMIGRATION_COURT", "USCIS")
RECOGNITION_STATUSES = ("ACTIVE", "CONDITIONAL", "LAPSED", "WITHDRAWN")
RECOGNITION_CONDITIONAL_REASONS = (
    "ANNUAL_REPORT_LATE",
    "STAFFING_DEFICIENCY",
    "COMPLAINT_UNDER_REVIEW",
)

# ---------------------------------------------------------------------------
# Representative
# ---------------------------------------------------------------------------
REP_TYPES = ("STAFF_ATTORNEY", "ACCREDITED_REP", "PRO_BONO_VOLUNTEER", "LAW_GRADUATE")
AUTHORIZATION_STATUSES = (
    "AUTHORIZED_ATTORNEY",
    "AUTHORIZED_ACCREDITED",
    "AUTHORIZED_SUPERVISED",
    "AUTHORIZATION_SUSPENDED",
    "UNAUTHORIZED",
)
REPRESENTATIVE_STATUSES = ("ACTIVE", "INACTIVE", "SUSPENDED")
DEFAULT_MAX_CASE_LOAD = 25
DEFAULT_MAX_SUPERVISEES = 10
DEFAULT_WEEKLY_CAPACITY_HOURS = 40

# ---------------------------------------------------------------------------
# Accreditation
# ---------------------------------------------------------------------------
ACCREDITATION_TYPES = ("PARTIAL", "FULL")
ACCREDITATION_STATUSES = (
    "PENDING",
    "APPROVED",
    "EXPIRING",
    "RENEWAL_PENDING",
    "SUSPENDED_BY_RECOGNITION",
    "EXPIRED",
    "REVOKED",
    "DENIED",
)
ACCREDITATION_REASONS = (
    "CREDENTIALS_VERIFIED",
    "TRAINING_INCOMPLETE",
    "BACKGROUND_ADVERSE",
    "CONDUCT_VIOLATION",
    "VOLUNTARY_SURRENDER",
    "RECOGNITION_LAPSE",
)
ACCREDITATION_TERM_DAYS = 1095

# ---------------------------------------------------------------------------
# IntakeScreening
# ---------------------------------------------------------------------------
CASE_TYPES = (
    "ASYLUM_DEFENSIVE",
    "ASYLUM_AFFIRMATIVE",
    "U_VISA",
    "VAWA_SELF_PETITION",
    "SIJS",
    "DACA_RENEWAL",
    "NATURALIZATION",
    "ADJUSTMENT_OF_STATUS",
    "BOND_HEARING",
    "REMOVAL_DEFENSE_OTHER",
)
ELIGIBILITY_VERDICTS = (
    "PENDING",
    "ELIGIBLE",
    "INELIGIBLE_NO_RELIEF",
    "INELIGIBLE_INCOME",
    "INELIGIBLE_JURISDICTION",
)
URGENCY_TIERS = ("ROUTINE", "ELEVATED", "URGENT", "EMERGENCY")
URGENCY_VARIANTS = ("STRICT_STATUTORY", "CALENDAR_INCLUSIVE")
INTAKE_STATUSES = (
    "DRAFT",
    "SCREENED",
    "ACCEPTED",
    "WAITLISTED",
    "DECLINED",
    "REFERRED_OUT",
    "WITHDRAWN",
    "WAITLIST_EXPIRED",
)
INTAKE_DECISION_REASONS = (
    "ACCEPTED_ON_MERIT",
    "ACCEPTED_DETAINED_PRIORITY",
    "CAPACITY_FULL",
    "OUTSIDE_SERVICE_AREA",
    "NO_LEGAL_RELIEF",
    "INCOME_ABOVE_THRESHOLD",
    "CONFLICT_OF_INTEREST",
    "CLIENT_WITHDREW",
)

# ---------------------------------------------------------------------------
# CaseMatter
# ---------------------------------------------------------------------------
REPRESENTATION_STATUSES = (
    "UNSTAFFED",
    "STAFFED",
    "SUPERVISED_STAFFED",
    "COVERAGE_GAP",
    "WITHDRAWN_FROM",
)
FILING_STATUSES = (
    "PRE_FILING",
    "EVIDENCE_GATHERING",
    "READY_TO_FILE",
    "FILED",
    "RFE_PENDING",
    "DECIDED",
    "APPEALED",
    "CLOSED_NO_FILING",
)
SLOT_POOLS = ("DETAINED_RESERVED", "GENERAL", "NONE")
READINESS_GATES = ("EVIDENCE_WEIGHTED_GATE", "CHECKLIST_STRICT_GATE")
MATTER_OUTCOMES = (
    "GRANTED",
    "DENIED",
    "ADMINISTRATIVELY_CLOSED",
    "WITHDRAWN",
    "TERMINATED",
    "REFERRED_TO_COURT",
)

# ---------------------------------------------------------------------------
# CaseAssignment
# ---------------------------------------------------------------------------
ASSIGNMENT_ROLES = ("LEAD", "CO_COUNSEL", "SUPERVISOR", "INTERPRETER_COORDINATOR")
ASSIGNMENT_STATUSES = ("PROPOSED", "ACTIVE", "SUSPENDED", "RELEASED")
SUPERVISION_SOURCES = ("NOT_REQUIRED", "EXPLICIT_LINK", "AUTO_SELECTED")
RELEASE_REASONS = (
    "CLIENT_WITHDREW",
    "MATTER_CLOSED",
    "RECOGNITION_LAPSE",
    "CASELOAD_REBALANCE",
    "AUTHORIZATION_REVOKED",
    "SUPERSEDED_BY_NEW_LEAD",
    "VOLUNTEER_UNAVAILABLE",
)

# ---------------------------------------------------------------------------
# EvidenceItem
# ---------------------------------------------------------------------------
EVIDENCE_ITEM_TYPES = (
    "IDENTITY_DOCUMENT",
    "COUNTRY_CONDITIONS",
    "MEDICAL_RECORD",
    "POLICE_REPORT",
    "WITNESS_STATEMENT",
    "TAX_RECORD",
    "CERTIFICATION_LETTER",
)
EVIDENCE_TIERS = ("REQUIRED", "SUPPORTING", "OPTIONAL")
EVIDENCE_STATUSES = (
    "REQUESTED",
    "RECEIVED",
    "TRANSLATED",
    "VERIFIED",
    "REJECTED",
    "WAIVED",
)
EVIDENCE_DISPOSITION_REASONS = (
    "ILLEGIBLE",
    "UNTRANSLATED",
    "INCONSISTENT_WITH_DECLARATION",
    "UNOBTAINABLE_COUNTRY_CONDITIONS",
    "CLIENT_SAFETY_RISK",
    "DUPLICATE",
)
WEIGHT_POINTS_MIN = 1
WEIGHT_POINTS_MAX = 10

# ---------------------------------------------------------------------------
# Declaration
# ---------------------------------------------------------------------------
DECLARATION_STATUSES = (
    "DRAFT",
    "IN_REVIEW",
    "REVISION_REQUESTED",
    "CERTIFIED",
    "WITHDRAWN",
)
DECLARATION_REVISION_REASONS = (
    "FACTUAL_GAP",
    "LANGUAGE_MISMATCH",
    "MISSING_READBACK",
    "EVIDENCE_INCONSISTENCY",
    "SUPERVISION_REQUIRED",
)

# ---------------------------------------------------------------------------
# InterpretationSession
# ---------------------------------------------------------------------------
INTERPRETER_SOURCES = ("STAFF", "VOLUNTEER", "CONTRACT", "TELEPHONIC")
SESSION_PURPOSES = (
    "INTAKE",
    "DECLARATION_READBACK",
    "RIGHTS_COUNSELING",
    "HEARING_PREP",
    "FACILITY_VISIT",
)
SESSION_STATUSES = ("SCHEDULED", "COMPLETED", "NO_SHOW", "CANCELLED")
SESSION_CLOSURE_REASONS = (
    "CLIENT_UNAVAILABLE",
    "INTERPRETER_UNAVAILABLE",
    "FACILITY_DENIED_ACCESS",
    "HEARING_CONTINUED",
    "LANGUAGE_MISMATCH",
)

# ---------------------------------------------------------------------------
# CalendarEvent
# ---------------------------------------------------------------------------
EVENT_TYPES = (
    "BIOMETRICS",
    "MASTER_CALENDAR_HEARING",
    "INDIVIDUAL_HEARING",
    "ASYLUM_INTERVIEW",
    "FILING_DEADLINE",
    "FACILITY_VISIT",
)
EVENT_STATUSES = (
    "SCHEDULED",
    "CONFIRMED",
    "CONTINUED",
    "COMPLETED",
    "MISSED",
    "CANCELLED",
)

# ---------------------------------------------------------------------------
# InformedDecision
# ---------------------------------------------------------------------------
DECISION_TYPES = (
    "FILE_AFFIRMATIVE",
    "PURSUE_RELIEF_IN_COURT",
    "ACCEPT_VOLUNTARY_DEPARTURE",
    "APPEAL_DECISION",
    "WITHDRAW_CASE",
    "DECLINE_RELIEF",
)
RISKS = (
    "REMOVAL_RISK",
    "DETENTION_RISK",
    "BAR_TO_FUTURE_RELIEF",
    "FEE_LOSS",
    "CRIMINAL_EXPOSURE",
    "FAMILY_SEPARATION",
    "DATA_DISCLOSURE",
)
ALTERNATIVES = (
    "DO_NOTHING",
    "SEEK_OTHER_COUNSEL",
    "ALTERNATIVE_RELIEF_PATH",
    "VOLUNTARY_DEPARTURE",
    "ADMINISTRATIVE_CLOSURE",
    "APPEAL",
)
INFORMED_DECISION_STATUSES = ("PENDING", "DOCUMENTED", "SUPERSEDED", "REVOKED")
REVOCATION_REASONS = (
    "CLIENT_CHANGED_MIND",
    "NEW_FACTS",
    "COUNSEL_ERROR",
    "LANGUAGE_ACCESS_DEFECT",
)

# ---------------------------------------------------------------------------
# GrantReport
# ---------------------------------------------------------------------------
DISCLOSURE_LEVELS = (
    "AGGREGATE_ONLY",
    "DEIDENTIFIED_CASE_LEVEL",
    "IDENTIFIED_WITH_CONSENT",
)
REPORT_STATUSES = ("DRAFT", "GENERATED", "SUBMITTED", "AMENDED")

OUTCOME_HISTOGRAM_KEYS = (
    "GRANTED",
    "DENIED",
    "ADMINISTRATIVELY_CLOSED",
    "WITHDRAWN",
    "TERMINATED",
    "REFERRED_TO_COURT",
    "NOT_YET_DECIDED",
)

# ---------------------------------------------------------------------------
# Standing clock / date literals used by the design recipes
# ---------------------------------------------------------------------------
CLOCK_DEFAULT_UTC = "2026-08-01T00:00:00.000Z"
CLOCK_BASE_UTC = "2026-08-03T09:00:00.000Z"
CLOCK_BASE_DATE = "2026-08-03"

# Interpretation billing: the hourly rate follows interpreter_source and the
# rare-language surcharge is 15 percent outside the five common languages.
INTERPRETER_HOURLY_CENTS = {
    "STAFF": 0,
    "VOLUNTEER": 0,
    "CONTRACT": 9500,
    "TELEPHONIC": 6200,
}
RARE_LANGUAGE_SURCHARGE_RATE = 0.15
COMMON_LANGUAGES = ("es", "fr", "pt", "zh", "ar")
BILLED_MINUTES_FLOOR = 30
BILLED_MINUTES_BLOCK = 15

# Grant reimbursement: 12,500 cents per direct hour, surcharge tier from base only.
REIMBURSEMENT_CENTS_PER_HOUR = 12500
SURCHARGE_TIER_1_MIN = 500000
SURCHARGE_TIER_2_MIN = 2000000

COVERAGE_GAP_LOOKAHEAD_DAYS = 14
