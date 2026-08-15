"""Domain types: entity TypedDicts, status enums, role enum (PRD Sections 2-4)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    RESEARCH_OPS_ADMIN = "ResearchOpsAdmin"
    RESEARCHER = "Researcher"
    MODERATOR = "Moderator"
    PARTICIPANT = "Participant"
    INCENTIVE_OFFICER = "IncentiveOfficer"
    LEGAL_COUNSEL = "LegalCounsel"


class ParticipantStatus(str, Enum):
    REGISTERED = "REGISTERED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    BANNED = "BANNED"


class ModeratorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class StudyStatus(str, Enum):
    DRAFT = "DRAFT"
    RECRUITING = "RECRUITING"
    CLOSED = "CLOSED"
    ANALYSIS = "ANALYSIS"
    COMPLETED = "COMPLETED"


class ApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    INFO_REQUESTED = "INFO_REQUESTED"
    APPROVED = "APPROVED"
    ENROLLED = "ENROLLED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class NdaAgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    RETIRED = "RETIRED"


class NdaSignatureStatus(str, Enum):
    PENDING = "PENDING"
    SIGNED = "SIGNED"
    VOIDED = "VOIDED"
    EXPIRED = "EXPIRED"


class BuildStatus(str, Enum):
    STAGED = "STAGED"
    RELEASED = "RELEASED"
    RETIRED = "RETIRED"


class AccessKeyStatus(str, Enum):
    ISSUED = "ISSUED"
    REDEEMED = "REDEEMED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class StationStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class SessionMode(str, Enum):
    REMOTE = "REMOTE"
    IN_LAB = "IN_LAB"


class SessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class BookingStatus(str, Enum):
    BOOKED = "BOOKED"
    WAITLISTED = "WAITLISTED"
    PROMOTED = "PROMOTED"
    ATTENDED = "ATTENDED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class InstrumentStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    RETIRED = "RETIRED"


class ResponseStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"


class TicketSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class TicketStatus(str, Enum):
    NEW = "NEW"
    TRIAGED = "TRIAGED"
    NEEDS_INFO = "NEEDS_INFO"
    ROUTED = "ROUTED"
    RESOLVED = "RESOLVED"
    WONT_FIX = "WONT_FIX"


class PriorityTier(str, Enum):
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"
    P4 = "P4"


class BacklogTarget(str, Enum):
    GAMEPLAY = "GAMEPLAY"
    PERFORMANCE = "PERFORMANCE"
    UX = "UX"
    AUDIO = "AUDIO"
    INFRA = "INFRA"


class PayoutStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    ISSUED = "ISSUED"
    VOID = "VOID"


class BreachSeverity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"


class BreachStatus(str, Enum):
    REPORTED = "REPORTED"
    UNDER_INVESTIGATION = "UNDER_INVESTIGATION"
    DISMISSED = "DISMISSED"
    SUBSTANTIATED = "SUBSTANTIATED"
    SANCTIONED = "SANCTIONED"


class SanctionType(str, Enum):
    WARNING = "WARNING"
    BAN = "BAN"


class ExposureEventType(str, Enum):
    KEY_ISSUED = "KEY_ISSUED"
    KEY_REDEEMED = "KEY_REDEEMED"
    KEY_REVOKED = "KEY_REVOKED"
    KEY_EXPIRED = "KEY_EXPIRED"


# --- Entity TypedDicts ------------------------------------------------------
# Primary resources carry id + created_at + updated_at + version (PRD §2.5).


class Participant(TypedDict, total=False):
    id: str
    email: str
    full_name: str
    age_years: int
    region_code: str
    platform_tags: List[str]
    verified_platform_tags: List[str]
    status: str
    no_show_strikes: int
    risk_score: int
    created_at: str
    updated_at: str
    version: int


class Moderator(TypedDict, total=False):
    id: str
    display_name: str
    email: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Study(TypedDict, total=False):
    id: str
    title: str
    code: str
    min_age: int
    max_age: int
    allowed_regions: List[str]
    required_platforms: List[str]
    cohort_capacity: int
    incentive_budget_cents: int
    status: str
    enrolled_count: int
    budget_committed_cents: int
    budget_spent_cents: int
    created_at: str
    updated_at: str
    version: int


class ScreeningApplication(TypedDict, total=False):
    id: str
    study_id: str
    participant_id: str
    status: str
    fit_score_provisional: int
    fit_score_final: Optional[int]
    pinned_nda_agreement_id: Optional[str]
    info_request_note: Optional[str]
    decision_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class NdaAgreement(TypedDict, total=False):
    id: str
    study_id: str
    version_label: str
    body_text: str
    status: str
    published_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class NdaSignature(TypedDict, total=False):
    id: str
    agreement_id: str
    participant_id: str
    study_id: str
    application_id: str
    status: str
    expires_at: str
    signed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class GameBuild(TypedDict, total=False):
    id: str
    study_id: str
    build_label: str
    max_keys: int
    key_ttl_hours: int
    status: str
    released_at: Optional[str]
    keys_active_count: int
    created_at: str
    updated_at: str
    version: int


class AccessKey(TypedDict, total=False):
    id: str
    build_id: str
    participant_id: str
    key_code: str
    status: str
    expires_at: str
    redeemed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LabStation(TypedDict, total=False):
    id: str
    station_code: str
    location: str
    equipment_tags: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class PlaytestSession(TypedDict, total=False):
    id: str
    study_id: str
    mode: str
    station_id: Optional[str]
    moderator_id: Optional[str]
    starts_at: str
    ends_at: str
    seat_capacity: int
    seats_taken: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SessionBooking(TypedDict, total=False):
    id: str
    session_id: str
    participant_id: str
    status: str
    no_show_recorded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SurveyQuestion(TypedDict):
    question_key: str
    weight: float
    max_points: int


class SurveyInstrument(TypedDict, total=False):
    id: str
    study_id: str
    title: str
    questions: List[SurveyQuestion]
    pass_threshold: float
    status: str
    created_at: str
    updated_at: str
    version: int


class SurveyAnswer(TypedDict):
    question_key: str
    points: float


class SurveyResponse(TypedDict, total=False):
    id: str
    instrument_id: str
    session_id: str
    participant_id: str
    answers: List[SurveyAnswer]
    weighted_score: Optional[float]
    score_pct: Optional[float]
    passed: Optional[bool]
    status: str
    submitted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FeedbackTicket(TypedDict, total=False):
    id: str
    study_id: str
    session_id: Optional[str]
    survey_response_id: Optional[str]
    title: str
    severity: str
    reach_count: int
    reproducibility_pct: float
    priority_score: Optional[float]
    priority_tier: Optional[str]
    backlog_target: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class IncentivePayout(TypedDict, total=False):
    id: str
    study_id: str
    participant_id: str
    amount_provisional_cents: int
    amount_final_cents: Optional[int]
    status: str
    created_by_user_id: str
    approved_by_user_id: Optional[str]
    issued_by_user_id: Optional[str]
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BreachCase(TypedDict, total=False):
    id: str
    participant_id: str
    study_id: str
    evidence_summary: str
    severity: str
    reported_by_user_id: str
    reported_by_role: str
    adjudicated_by_user_id: Optional[str]
    sanction_type: Optional[str]
    sanction_note: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only journal: id + created_at ONLY — no updated_at, no version (PRD §2.5).
class ExposureRecord(TypedDict, total=False):
    id: str
    participant_id: str
    build_id: str
    study_id: str
    event_type: str
    recorded_at: str
    created_at: str
