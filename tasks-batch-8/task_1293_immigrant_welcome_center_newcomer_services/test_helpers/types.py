"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.5, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List, Any


class UserRole(str, Enum):
    CENTER_ADMIN = "CenterAdmin"
    CASE_MANAGER = "CaseManager"
    INTAKE_SPECIALIST = "IntakeSpecialist"
    PARTNER_ORG = "PartnerOrg"
    CLIENT = "Client"
    FUNDER_AUDITOR = "FunderAuditor"


class ClientStatus(str, Enum):
    REGISTERED = "REGISTERED"
    ACTIVE = "ACTIVE"
    EXITED = "EXITED"


class StaffRoleLevel(str, Enum):
    ADMIN = "ADMIN"
    CASE_MANAGER = "CASE_MANAGER"
    INTAKE = "INTAKE"


class OrganizationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class CaseServiceStatus(str, Enum):
    INTAKE = "INTAKE"
    ASSESSED = "ASSESSED"
    PLANNING = "PLANNING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    OUTCOME_REVIEW = "OUTCOME_REVIEW"
    CLOSED = "CLOSED"


class CasePrivacyPosture(str, Enum):
    STANDARD = "STANDARD"
    RESTRICTED = "RESTRICTED"
    SEALED = "SEALED"


class AssessmentStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    SUPERSEDED = "SUPERSEDED"


class PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    COMPLETED = "COMPLETED"
    SUPERSEDED = "SUPERSEDED"


class NoteSensitivity(str, Enum):
    STANDARD = "STANDARD"
    CONFIDENTIAL = "CONFIDENTIAL"
    SEALED = "SEALED"


class RedactionStatus(str, Enum):
    VISIBLE = "VISIBLE"
    REDACTED = "REDACTED"


class ConsentScope(str, Enum):
    REFERRAL_SHARE = "REFERRAL_SHARE"
    ACCOMPANIMENT = "ACCOMPANIMENT"
    DATA_REPORTING = "DATA_REPORTING"


class ConsentStatus(str, Enum):
    GRANTED = "GRANTED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class ReferralStatus(str, Enum):
    DRAFT = "DRAFT"
    SENT = "SENT"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"
    SUSPENDED = "SUSPENDED"
    COMPLETED = "COMPLETED"
    WITHDRAWN = "WITHDRAWN"


class AppointmentStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class AppointmentKind(str, Enum):
    DOCUMENT_ID = "DOCUMENT_ID"
    ACCOMPANIMENT = "ACCOMPANIMENT"
    ORIENTATION = "ORIENTATION"
    BENEFITS = "BENEFITS"


class ProgramStatus(str, Enum):
    OPEN = "OPEN"
    FULL = "FULL"
    CLOSED = "CLOSED"


class ProgramKind(str, Enum):
    ESOL = "ESOL"
    WORKFORCE = "WORKFORCE"


class EnrollmentStatus(str, Enum):
    APPLIED = "APPLIED"
    ELIGIBLE = "ELIGIBLE"
    ENROLLED = "ENROLLED"
    COMPLETED = "COMPLETED"
    WITHDRAWN = "WITHDRAWN"
    DENIED = "DENIED"


class FeeStatus(str, Enum):
    PENDING = "PENDING"
    ARRANGED = "ARRANGED"
    WAIVED = "WAIVED"


class SessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    HELD = "HELD"
    CANCELLED = "CANCELLED"
    RECONCILED = "RECONCILED"


class WorkshopEnrollmentStatus(str, Enum):
    ENROLLED = "ENROLLED"
    WAITLISTED = "WAITLISTED"
    CANCELLED = "CANCELLED"
    ATTENDED = "ATTENDED"
    NO_SHOW = "NO_SHOW"


class ScreeningStatus(str, Enum):
    DRAFT = "DRAFT"
    SCREENED = "SCREENED"
    EXPLAINED = "EXPLAINED"


class ScreeningVariant(str, Enum):
    SELF_REPORTED = "SELF_REPORTED"
    VERIFIED = "VERIFIED"


class BenefitTier(str, Enum):
    TIER_A = "TIER_A"
    TIER_B = "TIER_B"
    TIER_C = "TIER_C"
    TIER_D = "TIER_D"


class ReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    RETURNED = "RETURNED"


# --- Entity TypedDicts (PRD §2.5 common fields; Room is the lone exception) ---

class Client(TypedDict, total=False):
    id: str
    full_name: str
    preferred_language: str
    household_size: int
    date_of_birth: str
    country_of_origin: Optional[str]
    arrival_date: Optional[str]
    household_head_id: Optional[str]
    status: str
    reportable: bool
    created_at: str
    updated_at: str
    version: int


class StaffMember(TypedDict, total=False):
    id: str
    full_name: str
    role_level: str
    clearance_level: int
    weekly_appointment_capacity: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Organization(TypedDict, total=False):
    id: str
    name: str
    service_categories: List[str]
    referral_capacity: int
    referral_slots_used: int
    referral_slots_open: int
    contact_email: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Room(TypedDict, total=False):
    # PRD §2.5: rooms carry id and created_at only — no updated_at, no version.
    id: str
    name: str
    capacity: int
    created_at: str


class Case(TypedDict, total=False):
    id: str
    client_id: str
    assigned_manager_id: str
    service_status: str
    privacy_posture: str
    intake_summary: Optional[str]
    acuity_rapid: Optional[float]
    acuity_verified: Optional[float]
    closed_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class NeedsAssessment(TypedDict, total=False):
    id: str
    case_id: str
    housing_score: int
    employment_score: int
    education_score: int
    language_score: int
    health_score: int
    status: str
    created_by_id: str
    verified_by_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CasePlan(TypedDict, total=False):
    id: str
    case_id: str
    title: str
    budgeted_hours: int
    status: str
    plan_revision: int
    basis_assessment_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CaseNote(TypedDict, total=False):
    id: str
    case_id: str
    author_id: str
    body: str
    sensitivity: str
    redaction_status: str
    created_at: str
    updated_at: str
    version: int


class Consent(TypedDict, total=False):
    id: str
    client_id: str
    scope: str
    status: str
    expires_at: Optional[str]
    revoked_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Referral(TypedDict, total=False):
    id: str
    case_id: str
    organization_id: str
    service_category: str
    notes: Optional[str]
    status: str
    sent_at: Optional[str]
    responded_at: Optional[str]
    warm_handoff_offered: bool
    handoff_confirmed_at: Optional[str]
    completed_at: Optional[str]
    ttl_days: int
    suspension_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Appointment(TypedDict, total=False):
    id: str
    case_id: str
    advocate_id: str
    referral_id: Optional[str]
    kind: str
    starts_at: str
    ends_at: str
    status: str
    completed_at: Optional[str]
    cancelled_by_system: bool
    created_at: str
    updated_at: str
    version: int


class Program(TypedDict, total=False):
    id: str
    name: str
    kind: str
    capacity: int
    base_fee_cents: int
    cost_per_completion_cents: int
    enrolled_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ProgramEnrollment(TypedDict, total=False):
    id: str
    case_id: str
    program_id: str
    status: str
    subsidy_pct: Optional[float]
    subsidized_fee_cents: Optional[int]
    fee_status: str
    denial_reason: Optional[str]
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WorkshopSession(TypedDict, total=False):
    id: str
    room_id: str
    title: str
    capacity: int
    starts_at: str
    ends_at: str
    status: str
    enrolled_count: int
    waitlist_count: int
    open_seats: int
    created_at: str
    updated_at: str
    version: int


class WorkshopEnrollment(TypedDict, total=False):
    id: str
    session_id: str
    case_id: str
    status: str
    waitlist_position: Optional[int]
    attended_marked_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BenefitScreening(TypedDict, total=False):
    id: str
    case_id: str
    household_size: int
    stated_annual_income_cents: int
    documented_annual_income_cents: Optional[int]
    variant_used: Optional[str]
    income_ratio: Optional[float]
    tier: Optional[str]
    eligible_programs: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class FunderReport(TypedDict, total=False):
    id: str
    period_start: str
    period_end: str
    funding_streams: List[Any]
    status: str
    lines: List[Any]
    stream_totals: List[Any]
    total_cost_cents: int
    reportable_client_count: int
    aggregate_client_count: int
    submitted_by_id: Optional[str]
    reviewed_by_id: Optional[str]
    created_at: str
    updated_at: str
    version: int
