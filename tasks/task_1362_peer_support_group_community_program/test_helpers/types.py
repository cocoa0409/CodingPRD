"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.5, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    PROGRAM_ADMIN = "ProgramAdmin"
    FACILITATOR = "Facilitator"
    PARTICIPANT = "Participant"
    CLINICAL_COORDINATOR = "ClinicalCoordinator"


class ProgramPosture(str, Enum):
    OPEN = "OPEN"
    CAUTION = "CAUTION"
    LOCKDOWN = "LOCKDOWN"


class ProgramFocusArea(str, Enum):
    GRIEF = "GRIEF"
    ADDICTION = "ADDICTION"
    ANXIETY = "ANXIETY"
    PARENTING = "PARENTING"
    CHRONIC_ILLNESS = "CHRONIC_ILLNESS"


class GroupStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    RETIRED = "RETIRED"


class Modality(str, Enum):
    IN_PERSON = "IN_PERSON"
    VIRTUAL = "VIRTUAL"
    HYBRID = "HYBRID"


class SessionStatus(str, Enum):
    DRAFT = "DRAFT"
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    COMPLETED_WITH_INCIDENT = "COMPLETED_WITH_INCIDENT"
    CANCELLED = "CANCELLED"


class RoomStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class FacilitatorStatus(str, Enum):
    APPLIED = "APPLIED"
    SCREENING = "SCREENING"
    IN_TRAINING = "IN_TRAINING"
    SUPERVISED_PRACTICE = "SUPERVISED_PRACTICE"
    CERTIFIED = "CERTIFIED"
    SUSPENDED = "SUSPENDED"
    WITHDRAWN = "WITHDRAWN"
    REJECTED = "REJECTED"


class CourseStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class ParticipantStatus(str, Enum):
    REGISTERED = "REGISTERED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DEACTIVATED = "DEACTIVATED"


class AgreementStatus(str, Enum):
    SIGNED = "SIGNED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class SeatStatus(str, Enum):
    RESERVED = "RESERVED"
    CONFIRMED = "CONFIRMED"
    WAITLISTED = "WAITLISTED"
    RELEASED = "RELEASED"
    CANCELLED = "CANCELLED"


class EnrollmentAgreementStatus(str, Enum):
    PENDING = "PENDING"
    SIGNED = "SIGNED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class AttendanceStatus(str, Enum):
    CHECKED_IN = "CHECKED_IN"
    ATTENDED = "ATTENDED"
    NO_SHOW = "NO_SHOW"
    VOIDED = "VOIDED"


class AccessModality(str, Enum):
    IN_PERSON = "IN_PERSON"
    VIRTUAL = "VIRTUAL"


class IncidentSeverity(str, Enum):
    STANDARD = "STANDARD"
    CRITICAL = "CRITICAL"


class IncidentCategory(str, Enum):
    SAFETY = "SAFETY"
    CONFIDENTIALITY = "CONFIDENTIALITY"
    HARASSMENT = "HARASSMENT"
    MEDICAL = "MEDICAL"
    OTHER = "OTHER"


class IncidentStatus(str, Enum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"
    ESCALATED_TO_CLINICAL = "ESCALATED_TO_CLINICAL"


class ReferralStatus(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    COMPLETED = "COMPLETED"


class ReasonCode(str, Enum):
    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    CRISIS = "CRISIS"
    MEDICAL = "MEDICAL"
    RISK_OF_HARM = "RISK_OF_HARM"


# --- Entity TypedDicts ---
# Standard resources carry id + created_at + updated_at + version (PRD §2.5).


class Program(TypedDict, total=False):
    id: str
    name: str
    focus_area: str
    posture: str
    active_critical_incident_count: int
    active_standard_incident_count: int
    scheduled_session_count: int
    created_at: str
    updated_at: str
    version: int


class PeerGroup(TypedDict, total=False):
    id: str
    program_id: str
    name: str
    modality: str
    base_capacity: int
    required_facilitator_level: int
    status: str
    active_enrollment_count: int
    created_at: str
    updated_at: str
    version: int


class Session(TypedDict, total=False):
    id: str
    group_id: str
    room_id: Optional[str]
    start_at: str
    end_at: str
    primary_facilitator_id: str
    cofacilitator_id: Optional[str]
    status: str
    reserved_seats: int
    confirmed_seats: int
    effective_capacity: int
    virtual_link_token: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Room(TypedDict, total=False):
    id: str
    name: str
    physical_capacity: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Facilitator(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    status: str
    level: int
    supervision_required: bool
    application_submitted_at: str
    certified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TrainingCourse(TypedDict, total=False):
    id: str
    code: str
    title: str
    credit_hours: int
    level_weight: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TrainingCompletion(TypedDict, total=False):
    id: str
    facilitator_id: str
    course_id: str
    completed_at: str
    score: int
    created_at: str
    updated_at: str
    version: int


class SupervisionReview(TypedDict, total=False):
    id: str
    facilitator_id: str
    reviewer_id: str
    occurred_at: str
    rating: int
    clears_supervision_required: bool
    created_at: str
    updated_at: str
    version: int


class Participant(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    household_size: int
    status: str
    attendance_streak: int
    total_no_shows: int
    current_agreement_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict, total=False):
    id: str
    group_id: str
    participant_id: str
    seat_status: str
    agreement_status: str
    reserved_at: str
    confirmed_at: Optional[str]
    waitlist_position: Optional[int]
    created_at: str
    updated_at: str
    version: int


class AttendanceRecord(TypedDict, total=False):
    id: str
    session_id: str
    participant_id: str
    check_in_at: str
    check_out_at: Optional[str]
    access_modality: str
    status: str
    created_at: str
    updated_at: str
    version: int


class IncidentReport(TypedDict, total=False):
    id: str
    session_id: str
    raised_by_facilitator_id: str
    severity: str
    category: str
    description: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ClinicalReferral(TypedDict, total=False):
    id: str
    participant_id: str
    source_incident_id: Optional[str]
    reason_code: str
    status: str
    clinical_notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Immutable records (PRD §2.5): only id + created_at; no updated_at, no version.


class ConfidentialityAgreement(TypedDict, total=False):
    id: str
    participant_id: str
    signed_at: str
    expires_at: str
    status: str
    agreement_version: int
    created_at: str


class EvaluationSurvey(TypedDict, total=False):
    id: str
    session_id: str
    participant_id: str
    overall_rating: int
    facilitator_rating: int
    modality_rating: int
    free_text: Optional[str]
    submitted_at: str
    created_at: str
