"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Status enums ---

class ProgramStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    RETIRED = "RETIRED"


class ProgramVersionStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    SUPERSEDED = "SUPERSEDED"


class FacilitatorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class CohortStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    LOCKED = "LOCKED"
    RUNNING = "RUNNING"
    DELIVERED = "DELIVERED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class SessionStatus(str, Enum):
    PLANNED = "PLANNED"
    HELD = "HELD"
    SKIPPED = "SKIPPED"


class SessionAssignmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


class RegistrationStatus(str, Enum):
    WAITLISTED = "WAITLISTED"
    ENROLLED = "ENROLLED"
    CONFIRMED = "CONFIRMED"
    ATTENDED = "ATTENDED"
    NO_SHOW = "NO_SHOW"
    WITHDRAWN = "WITHDRAWN"
    CANCELLED = "CANCELLED"


class AssessmentStatus(str, Enum):
    GRADED = "GRADED"
    VOIDED = "VOIDED"


class AssessmentOutcome(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class CertificateStatus(str, Enum):
    ISSUED = "ISSUED"
    REVOKED = "REVOKED"


class EnterpriseContractStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXHAUSTED = "EXHAUSTED"
    CLOSED = "CLOSED"


class InvoiceVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class InvoiceStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"
    VOID = "VOID"


class ProgramCategory(str, Enum):
    LEADERSHIP = "LEADERSHIP"
    TECHNICAL = "TECHNICAL"
    COMPLIANCE = "COMPLIANCE"
    SALES = "SALES"


class DeliveryMode(str, Enum):
    VIRTUAL = "VIRTUAL"
    ONSITE = "ONSITE"
    HYBRID = "HYBRID"


class PricingModel(str, Enum):
    PER_SEAT = "PER_SEAT"
    FLAT = "FLAT"


class BillingMode(str, Enum):
    CONTRACT = "CONTRACT"
    SELF_PAY = "SELF_PAY"


class UserRole(str, Enum):
    ProgramDesigner = "ProgramDesigner"
    SchedulingCoordinator = "SchedulingCoordinator"
    Facilitator = "Facilitator"
    Learner = "Learner"
    FinanceManager = "FinanceManager"


# --- Entity TypedDicts (common_fields: true => id/created_at/updated_at/version) ---

class Program(TypedDict):
    id: str
    title: str
    category: str
    delivery_mode: str
    ceu_credits: float
    is_custom: bool
    status: str
    active_version_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProgramVersion(TypedDict):
    id: str
    program_id: str
    version_label: str
    duration_hours: float
    pricing_model: str
    per_seat_cents: int
    flat_fee_cents: int
    materials_kit_cents: int
    min_seats: int
    pass_threshold_pct: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Facilitator(TypedDict):
    id: str
    full_name: str
    email: str
    certified_categories: List[str]
    travel_base_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Cohort(TypedDict):
    id: str
    program_version_id: str
    lead_facilitator_id: str
    contract_id: Optional[str]
    seat_capacity: int
    waitlist_capacity: int
    delivery_mode: str
    starts_at: str
    ends_at: str
    enroll_deadline: str
    seats_reserved: int
    seats_confirmed: int
    seats_waitlisted: int
    nps_score: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Session(TypedDict):
    id: str
    cohort_id: str
    title: str
    starts_at: str
    ends_at: str
    room_or_url: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SessionAssignment(TypedDict):
    id: str
    session_id: str
    facilitator_id: str
    role: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Registration(TypedDict):
    id: str
    cohort_id: str
    learner_email: str
    learner_name: str
    contract_id: Optional[str]
    billing_mode: str
    seat_price_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Assessment(TypedDict):
    id: str
    registration_id: str
    raw_score: int
    max_score: int
    percent_score: float
    outcome: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Certificate(TypedDict):
    id: str
    registration_id: str
    assessment_id: str
    ceu_awarded: float
    serial: str
    status: str
    created_at: str
    updated_at: str
    version: int


class EnterpriseContract(TypedDict):
    id: str
    client_name: str
    budget_cents: int
    committed_cents: int
    remaining_cents: int
    is_recurring: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    cohort_id: str
    contract_id: Optional[str]
    tuition_cents: int
    materials_cents: int
    travel_cents: int
    total_cents: int
    variant: str
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only, carries ONLY id + created_at (no updated_at, no version)
class Evaluation(TypedDict):
    id: str
    registration_id: str
    cohort_id: str
    nps_rating: int
    comment: str
    created_at: str
