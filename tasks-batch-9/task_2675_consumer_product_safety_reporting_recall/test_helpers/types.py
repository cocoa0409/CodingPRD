"""Roles, enumerations and state names for the product safety domain."""

from enum import Enum


class Role(str, Enum):
    """The seven roles the service recognises."""

    PROGRAM_ADMIN = "ProgramAdmin"
    INTAKE_SPECIALIST = "IntakeSpecialist"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    SAFETY_DIRECTOR = "SafetyDirector"
    FIELD_AUDITOR = "FieldAuditor"
    PENALTY_COUNSEL = "PenaltyCounsel"
    RETAILER_REP = "RetailerRep"


ALL_ROLES = tuple(role.value for role in Role)

# --- ProductModel -----------------------------------------------------------
PRODUCT_CATEGORIES = (
    "KITCHEN_APPLIANCE",
    "JUVENILE_PRODUCT",
    "POWER_TOOL",
    "SPORTING_GOODS",
    "HOME_ELECTRONICS",
)
HAZARD_POSTURES = ("MONITORED", "RESTRICTED", "FROZEN")

# --- Retailer ---------------------------------------------------------------
CHANNEL_TYPES = ("BIG_BOX", "ONLINE_MARKETPLACE", "SPECIALTY", "DISTRIBUTOR")
COMPLIANCE_POSTURES = ("CLEAR", "STOP_SALE_ACTIVE", "DELINQUENT")

# --- IncidentReport ---------------------------------------------------------
REPORT_CHANNELS = ("CONSUMER_HOTLINE", "WEB_FORM", "RETAILER", "MEDICAL_EXAMINER")
INJURY_CLASSES = (
    "NO_INJURY",
    "FIRST_AID",
    "MEDICAL_TREATMENT",
    "HOSPITALIZATION",
    "FATALITY",
)
HAZARD_CODES = (
    "LACERATION",
    "BURN",
    "CHOKING",
    "ELECTRIC_SHOCK",
    "FALL",
    "ENTRAPMENT",
)
INCIDENT_STATUSES = (
    "INTAKE",
    "CLASSIFIED",
    "CLUSTERED",
    "ESCALATED",
    "MERGED_DUPLICATE",
    "CLOSED_NO_ACTION",
)
INCIDENT_DISPOSITIONS = ("MERGED_DUPLICATE", "CLOSED_NO_ACTION")

# --- HazardPattern ----------------------------------------------------------
ANALYSIS_BASES = ("PRELIMINARY", "FINAL")
PATTERN_STATUSES = ("ANALYZED", "CONFIRMED", "DISMISSED", "SUPERSEDED")
PATTERN_DECISIONS = ("CONFIRMED", "DISMISSED")

# --- ReportabilityEvaluation ------------------------------------------------
STANDARD_BASES = (
    "DEFECT",
    "UNREASONABLE_RISK",
    "NONCOMPLIANCE",
    "VOLUNTARY_STANDARD_FAILURE",
)
EVALUATION_STATUSES = ("OPEN", "IN_REVIEW", "REPORTABLE", "NOT_REPORTABLE")
DETERMINATIONS = ("REPORTABLE", "NOT_REPORTABLE")

# --- SectionReport ----------------------------------------------------------
CORRECTIVE_ACTION_TYPES = ("REPAIR", "REPLACE", "REFUND", "RETROFIT_KIT")
SECTION_REPORT_STATUSES = ("DRAFT", "SUBMITTED", "ACCEPTED", "RETURNED_FOR_INFO")
REVIEW_DECISIONS = ("ACCEPTED", "RETURNED_FOR_INFO")

# --- Recall -----------------------------------------------------------------
REMEDY_OPTIONS = ("REPAIR", "REPLACE", "REFUND", "RETROFIT_KIT")
PLAN_STATUSES = ("DRAFT", "SUBMITTED", "APPROVED", "MONITORING", "CLOSED")
NOTIFICATION_STATUSES = ("NOT_STARTED", "IN_PROGRESS", "DEFICIENT", "SATISFIED")
EFFECTIVENESS_FLAGS = ("PENDING", "MET", "SHORTFALL")

# --- RetailerNotification ---------------------------------------------------
RETAILER_NOTIFICATION_STATUSES = (
    "PENDING",
    "ISSUED",
    "ACKNOWLEDGED",
    "VERIFIED",
    "DELINQUENT",
)

# --- AuditVisit -------------------------------------------------------------
VISIT_STATUSES = ("SCHEDULED", "COMPLETED")
VISIT_VERDICTS = ("PENDING", "PASS", "FAIL")
COMPLETION_VERDICTS = ("PASS", "FAIL")

# --- ConsumerNotice ---------------------------------------------------------
NOTICE_CHANNELS = (
    "DIRECT_NOTICE",
    "PRESS_RELEASE",
    "REGISTRATION_CARD",
    "WEB_POSTING",
)
NOTICE_STATUSES = ("SCHEDULED", "RELEASED", "SUPERSEDED")

# --- RemedyClaim ------------------------------------------------------------
REMEDY_TYPES = ("REPAIR", "REPLACE", "REFUND", "RETROFIT_KIT")
CLAIM_STATUSES = ("SUBMITTED", "APPROVED", "FULFILLED", "VOID")

# --- ProgressReport ---------------------------------------------------------
EFFECTIVENESS_BASES = ("UNITS_BASIS", "PARTICIPATION_BASIS")
PROGRESS_REPORT_STATUSES = ("DRAFT", "SUBMITTED", "ACCEPTED")
ASSESSMENTS = ("PENDING", "ON_TRACK", "BELOW_TARGET", "CRITICAL")

# --- CivilPenaltyCase -------------------------------------------------------
PENALTY_CASE_STATUSES = ("ASSESSMENT_OPEN", "OFFER_MADE", "COUNTERED", "AGREED")
OFFER_PARTIES = ("AGENCY", "RESPONDENT")
OFFER_RESOLUTIONS = ("WITHDRAWN", "ACCEPTED")
CREDIT_TIERS = ("TIER_1", "TIER_2", "TIER_3")

# Common properties every persisted record carries.
COMMON_FIELDS = ("id", "created_at", "updated_at", "version")
