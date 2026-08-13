"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.5, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    PRACTICE_ADMIN = "PracticeAdmin"
    COACH = "Coach"
    FAMILY_MEMBER = "FamilyMember"
    EXTERNAL_CONTACT = "ExternalContact"


class FamilyStatus(str, Enum):
    INTAKE = "INTAKE"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class BillingStatus(str, Enum):
    CURRENT = "CURRENT"
    DELINQUENT = "DELINQUENT"


class ClientTrack(str, Enum):
    INDIVIDUAL = "INDIVIDUAL"
    GROUP = "GROUP"
    HYBRID = "HYBRID"


class ClientStatus(str, Enum):
    INTAKE = "INTAKE"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    DISCHARGED = "DISCHARGED"


class CredentialLevel(str, Enum):
    ASSOCIATE = "ASSOCIATE"
    CERTIFIED = "CERTIFIED"
    SUPERVISOR = "SUPERVISOR"


class CoachStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    SUPERVISION_DEFICIT = "SUPERVISION_DEFICIT"
    INACTIVE = "INACTIVE"


class IntakeStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    NEEDS_REVISION = "NEEDS_REVISION"


class PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    PROPOSED = "PROPOSED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    TERMINATED = "TERMINATED"
    SUPERSEDED = "SUPERSEDED"


class PlanPosture(str, Enum):
    SCHEDULABLE = "SCHEDULABLE"
    SCHEDULING_BLOCKED = "SCHEDULING_BLOCKED"


class Cadence(str, Enum):
    WEEKLY = "WEEKLY"
    BIWEEKLY = "BIWEEKLY"


class GoalStatus(str, Enum):
    SET = "SET"
    IN_PROGRESS = "IN_PROGRESS"
    ACHIEVED = "ACHIEVED"
    DROPPED = "DROPPED"
    CARRIED_FORWARD = "CARRIED_FORWARD"


class PackageTrack(str, Enum):
    INDIVIDUAL = "INDIVIDUAL"
    GROUP = "GROUP"


class PackageStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXHAUSTED = "EXHAUSTED"
    EXPIRED = "EXPIRED"
    REFUNDED = "REFUNDED"


class AttendanceState(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED_EARLY = "CANCELLED_EARLY"
    CANCELLED_LATE = "CANCELLED_LATE"
    NO_SHOW = "NO_SHOW"


class SessionBillingState(str, Enum):
    RESERVED = "RESERVED"
    CONSUMED = "CONSUMED"
    RETURNED = "RETURNED"
    FORFEITED = "FORFEITED"


class CheckInStatus(str, Enum):
    PENDING = "PENDING"
    SUBMITTED_ON_TIME = "SUBMITTED_ON_TIME"
    SUBMITTED_LATE = "SUBMITTED_LATE"
    MISSED = "MISSED"
    ACKNOWLEDGED = "ACKNOWLEDGED"


class ContactType(str, Enum):
    SCHOOL = "SCHOOL"
    CLINICIAN = "CLINICIAN"


class ContactStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class ConsentScope(str, Enum):
    PROGRESS_ONLY = "PROGRESS_ONLY"
    GOALS_AND_PROGRESS = "GOALS_AND_PROGRESS"
    FULL_PLAN = "FULL_PLAN"


class ConsentStatus(str, Enum):
    PENDING_SIGNATURE = "PENDING_SIGNATURE"
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"


class NoteTopic(str, Enum):
    PROGRESS = "PROGRESS"
    GOALS = "GOALS"
    PLAN_DETAIL = "PLAN_DETAIL"


class NoteStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    SHARED = "SHARED"
    SEALED = "SEALED"


class WorkshopStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    LOCKED = "LOCKED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class EnrollmentStatus(str, Enum):
    ENROLLED = "ENROLLED"
    WAITLISTED = "WAITLISTED"
    DROPPED = "DROPPED"
    REFUNDED = "REFUNDED"


class BillingSource(str, Enum):
    PACKAGE_CREDIT = "PACKAGE_CREDIT"
    MONEY = "MONEY"
    NONE = "NONE"


class SupervisionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    HELD = "HELD"
    VERIFIED = "VERIFIED"
    CANCELLED = "CANCELLED"


# --- Entity payloads (common_fields: id + created_at + updated_at + version) ---


class Family(TypedDict):
    id: str
    account_name: str
    primary_email: str
    status: str
    total_charged_cents: int
    total_refunded_cents: int
    total_paid_cents: int
    outstanding_balance_cents: int
    billing_status: str
    created_at: str
    updated_at: str
    version: int


class Client(TypedDict):
    id: str
    family_id: str
    full_name: str
    date_of_birth: str
    track: str
    status: str
    active_plan_id: Optional[str]
    checkin_streak: int
    rolling_progress_index: Optional[int]
    cumulative_progress_index: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Coach(TypedDict):
    id: str
    full_name: str
    credential_level: str
    status: str
    active_caseload: int
    caseload_cap: int
    required_supervision_hours: int
    verified_supervision_hours_30d: float
    created_at: str
    updated_at: str
    version: int


class IntakeAssessment(TypedDict):
    id: str
    client_id: str
    presenting_concerns: str
    baseline_score: int
    review_notes: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CoachingPlan(TypedDict):
    id: str
    client_id: str
    coach_id: str
    intake_id: str
    cadence: str
    revision_number: int
    status: str
    posture: str
    revision_recommended: bool
    activated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Goal(TypedDict):
    id: str
    plan_id: str
    title: str
    target_date: str
    status: str
    carried_to_plan_id: Optional[str]
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Package(TypedDict):
    id: str
    family_id: str
    track: str
    credits_total: int
    credits_consumed: int
    credits_forfeited: int
    credits_remaining: int
    reserved_count: int
    price_paid_cents: int
    unit_gross_cents: int
    per_credit_value_cents: int
    purchased_at: str
    expires_at: str
    refund_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Session(TypedDict):
    id: str
    plan_id: str
    coach_id: str
    package_id: str
    scheduled_start: str
    scheduled_end: str
    attendance_state: str
    billing_state: str
    cancellation_fee_cents: int
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CheckIn(TypedDict):
    id: str
    plan_id: str
    due_at: str
    submitted_at: Optional[str]
    outcome_note: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ProgressSnapshot(TypedDict):
    """Append-only measurement record: id + created_at only (PRD §2.5).

    Both updated_at and version are absent from snapshots, because a snapshot
    is never mutated after it is written.
    """

    id: str
    client_id: str
    window_start: str
    window_end: str
    goals_considered: int
    goals_achieved: int
    checkins_considered: int
    checkins_on_time: int
    rolling_index: Optional[int]
    cumulative_index: Optional[int]
    created_at: str


class CoordinationContact(TypedDict):
    id: str
    family_id: str
    name: str
    organization: str
    contact_type: str
    email: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ConsentGrant(TypedDict):
    id: str
    family_id: str
    contact_id: str
    scope: str
    status: str
    signed_at: Optional[str]
    expires_at: str
    created_at: str
    updated_at: str
    version: int


class CoordinationNote(TypedDict):
    id: str
    client_id: str
    author_coach_id: str
    topic: str
    body: str
    status: str
    shared_with_contact_id: Optional[str]
    shared_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Workshop(TypedDict):
    id: str
    title: str
    coach_id: str
    capacity: int
    window_start: str
    window_end: str
    price_cents: int
    seats_taken: int
    status: str
    created_at: str
    updated_at: str
    version: int


class WorkshopEnrollment(TypedDict):
    id: str
    workshop_id: str
    client_id: str
    status: str
    waitlist_position: Optional[int]
    billing_source: str
    charged_cents: int
    created_at: str
    updated_at: str
    version: int


class SupervisionRecord(TypedDict):
    id: str
    coach_id: str
    supervisor_coach_id: str
    scheduled_at: str
    hours: float
    status: str
    verified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
