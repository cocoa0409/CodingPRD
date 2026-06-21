"""Domain types: entity TypedDicts, status enums, role enum.

Mirrors the resource shapes described in the Weight Management & Nutrition
Program PRD. Append-only event records (weigh-ins and messages) carry only
``id`` and ``created_at`` — never ``updated_at`` or ``version``.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Roles ────────────────────────────────────────────
class UserRole(str, Enum):
    PROGRAM_ADMIN = "ProgramAdmin"
    CLINICIAN = "Clinician"
    BILLING_AGENT = "BillingAgent"
    COACH = "Coach"
    MEMBER = "Member"


# ─── Status enums ─────────────────────────────────────
class MemberStatus(str, Enum):
    REGISTERED = "REGISTERED"
    INTAKE_PENDING = "INTAKE_PENDING"
    ENROLLED = "ENROLLED"
    GRADUATED = "GRADUATED"
    WITHDRAWN = "WITHDRAWN"


class PlanTier(str, Enum):
    COACHING = "COACHING"
    RX = "RX"
    MEAL = "MEAL"


class CoachSpecialty(str, Enum):
    GENERAL = "GENERAL"
    DIETITIAN = "DIETITIAN"
    CLINICAL = "CLINICAL"


class IntakeStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    NEEDS_REVISION = "NEEDS_REVISION"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class RiskBand(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"


class ClinicalStatus(str, Enum):
    PENDING_CLINICAL = "PENDING_CLINICAL"
    ACTIVE = "ACTIVE"
    GRADUATED = "GRADUATED"
    WITHDRAWN = "WITHDRAWN"


class BillingStatus(str, Enum):
    UNBILLED = "UNBILLED"
    CURRENT = "CURRENT"
    PAST_DUE = "PAST_DUE"
    CLOSED = "CLOSED"


class GoalKind(str, Enum):
    PRIMARY = "PRIMARY"
    SECONDARY = "SECONDARY"


class GoalStatus(str, Enum):
    OPEN = "OPEN"
    ACHIEVED = "ACHIEVED"
    CLOSED = "CLOSED"


class MilestoneStatus(str, Enum):
    PENDING = "PENDING"
    ACHIEVED = "ACHIEVED"
    VOIDED = "VOIDED"


class CoachAssignmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ENDED = "ENDED"


class MessageThreadStatus(str, Enum):
    OPEN = "OPEN"
    ARCHIVED = "ARCHIVED"


class InvoiceStatus(str, Enum):
    ISSUED = "ISSUED"
    PAID = "PAID"
    VOID = "VOID"


class EligibilityStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class RxStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ISSUED = "ISSUED"
    DENIED = "DENIED"
    REVOKED = "REVOKED"


class SenderRole(str, Enum):
    MEMBER = "MEMBER"
    COACH = "COACH"


# ─── Entity TypedDicts (common_fields: true → id+created_at+updated_at+version) ───
class Program(TypedDict):
    id: str
    name: str
    description: Optional[str]
    current_utc: str
    coach_max_active_members: int
    created_at: str
    updated_at: str
    version: int


class PlanCatalogItem(TypedDict):
    id: str
    program_id: str
    tier: str
    name: str
    monthly_fee_cents: int
    enrollment_fee_cents: int
    requires_rx: bool
    hsa_fsa_default_eligible: bool
    active: bool
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict):
    id: str
    program_id: str
    full_name: str
    email: str
    height_cm: float
    baseline_weight_kg: Optional[float]
    latest_weight_kg: Optional[float]
    latest_lean_mass_kg: Optional[float]
    scale_progress_pct: float
    lean_adjusted_progress_pct: float
    account_balance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Coach(TypedDict):
    id: str
    program_id: str
    full_name: str
    email: str
    specialty: str
    active_member_count: int
    accepting: bool
    created_at: str
    updated_at: str
    version: int


class IntakeAssessment(TypedDict):
    id: str
    member_id: str
    program_id: str
    weight_kg: float
    bmi: float
    comorbidity_count: int
    risk_band: str
    review_notes: Optional[str]
    revision_round: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict):
    id: str
    member_id: str
    program_id: str
    plan_id: str
    intake_assessment_id: str
    billing_anchor_utc: Optional[str]
    cycle_length_days: int
    clinical_status: str
    billing_status: str
    cycles_billed: int
    graduation_eligible: bool
    created_at: str
    updated_at: str
    version: int


class Goal(TypedDict):
    id: str
    enrollment_id: str
    member_id: str
    kind: str
    target_weight_kg: float
    progress_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Milestone(TypedDict):
    id: str
    goal_id: str
    enrollment_id: str
    threshold_pct: int
    achieved_at_utc: Optional[str]
    achieved_weight_kg: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class CoachAssignment(TypedDict):
    id: str
    enrollment_id: str
    coach_id: str
    member_id: str
    assigned_at_utc: str
    ended_at_utc: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class MessageThread(TypedDict):
    id: str
    coach_assignment_id: str
    enrollment_id: str
    subject: str
    message_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    enrollment_id: str
    member_id: str
    cycle_index: int
    period_start_utc: str
    period_end_utc: str
    line_items: List[dict]
    subtotal_cents: int
    hsa_fsa_eligible_cents: int
    prorated: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class EligibilityDetermination(TypedDict):
    id: str
    member_id: str
    program_id: str
    enrollment_id: str
    composite_score: float
    hsa_fsa_eligible: bool
    determined_utc: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class RxAuthorization(TypedDict):
    id: str
    enrollment_id: str
    member_id: str
    eligibility_determination_id: str
    clinician_user_id: Optional[str]
    qualifying_bmi: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


# ─── Append-only event records (only id + created_at) ───
class WeighIn(TypedDict):
    id: str
    enrollment_id: str
    member_id: str
    weight_kg: float
    body_fat_pct: Optional[float]
    lean_mass_kg: Optional[float]
    recorded_utc: str
    counts: bool
    created_at: str


class Message(TypedDict):
    id: str
    message_thread_id: str
    sender_role: str
    sender_user_id: str
    body: str
    posted_utc: str
    created_at: str
