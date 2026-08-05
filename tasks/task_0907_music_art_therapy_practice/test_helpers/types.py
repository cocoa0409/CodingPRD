"""Domain types: entity TypedDicts, status enums, and the role enum.

All types reflect the Music & Art Therapy Practice API contract. Every entity
in this system is mutable and therefore carries id/created_at/updated_at/version.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --------------------------------------------------------------------------- roles
class UserRole(str, Enum):
    INTAKE_COORDINATOR = "IntakeCoordinator"
    THERAPIST = "Therapist"
    CLINICAL_DIRECTOR = "ClinicalDirector"
    BILLING_SPECIALIST = "BillingSpecialist"


# --------------------------------------------------------------------------- enums
class Discipline(str, Enum):
    MUSIC = "MUSIC"
    ART = "ART"


class PayerType(str, Enum):
    INSURANCE = "INSURANCE"
    SELF_PAY = "SELF_PAY"


class ClientStatus(str, Enum):
    INTAKE = "INTAKE"
    ACTIVE = "ACTIVE"
    DISCHARGED = "DISCHARGED"


class ReferralStatus(str, Enum):
    RECEIVED = "RECEIVED"
    ASSESSED = "ASSESSED"
    CONVERTED = "CONVERTED"
    DECLINED = "DECLINED"


class Recommendation(str, Enum):
    THERAPY_RECOMMENDED = "THERAPY_RECOMMENDED"
    NOT_APPROPRIATE = "NOT_APPROPRIATE"


class PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    UNDER_REVISION = "UNDER_REVISION"
    DISCHARGED = "DISCHARGED"
    SUPERSEDED = "SUPERSEDED"


class GoalStatus(str, Enum):
    OPEN = "OPEN"
    MET = "MET"
    DISCONTINUED = "DISCONTINUED"


class MaterialCategory(str, Enum):
    INSTRUMENT = "INSTRUMENT"
    ART_SUPPLY = "ART_SUPPLY"


class ContractType(str, Enum):
    FACILITY = "FACILITY"
    SCHOOL = "SCHOOL"


class Modality(str, Enum):
    INDIVIDUAL = "INDIVIDUAL"
    GROUP = "GROUP"


class SchedulingStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class BillingStatus(str, Enum):
    UNBILLED = "UNBILLED"
    BILLED = "BILLED"
    ADJUDICATED = "ADJUDICATED"


class EnrollmentStatus(str, Enum):
    ENROLLED = "ENROLLED"
    ATTENDED = "ATTENDED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class NoteStatus(str, Enum):
    DRAFT = "DRAFT"
    SIGNED = "SIGNED"


class SuperbillStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ADJUDICATED = "ADJUDICATED"
    VOIDED = "VOIDED"


# ------------------------------------------------------------------------- entities
class Therapist(TypedDict):
    id: str
    full_name: str
    discipline: str
    credential: str
    created_at: str
    updated_at: str
    version: int


class Client(TypedDict):
    id: str
    full_name: str
    dob: str
    payer_type: str
    household_income_cents: int
    household_size: int
    insurance_payer_name: Optional[str]
    insurance_coinsurance_pct: float
    insurance_contracted_rate_cents: int
    insurance_visits_authorized: int
    insurance_visits_used: int
    insurance_visits_remaining: int
    status: str
    discharge_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Referral(TypedDict):
    id: str
    client_id: str
    referral_source: str
    reason: str
    referred_discipline: str
    assessed_by_therapist_id: Optional[str]
    recommendation: Optional[str]
    baseline_score: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class TreatmentPlan(TypedDict):
    id: str
    client_id: str
    referral_id: str
    discipline: str
    weekly_frequency: int
    revision_count: int
    revision_note: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Goal(TypedDict):
    id: str
    plan_id: str
    description: str
    target_sessions: int
    weight: float
    progress_attendance: float
    progress_rubric: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Room(TypedDict):
    id: str
    name: str
    capacity: int
    created_at: str
    updated_at: str
    version: int


class MaterialItem(TypedDict):
    id: str
    name: str
    category: str
    on_hand_quantity: int
    reserved_quantity: int
    available_quantity: int
    unit_charge_cents: int
    created_at: str
    updated_at: str
    version: int


class Contract(TypedDict):
    id: str
    party_name: str
    contract_type: str
    budget_cents: int
    rate_cents_per_session: int
    spent_cents: int
    created_at: str
    updated_at: str
    version: int


class Session(TypedDict):
    id: str
    therapist_id: str
    room_id: str
    plan_id: str
    goal_id: str
    contract_id: Optional[str]
    material_item_id: Optional[str]
    material_qty: int
    modality: str
    start_utc: str
    end_utc: str
    capacity: int
    attended_count: int
    scheduling_status: str
    billing_status: str
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict):
    id: str
    session_id: str
    client_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ProgressNote(TypedDict):
    id: str
    enrollment_id: str
    narrative: str
    rubric_score: int
    outcome_rating: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Superbill(TypedDict):
    id: str
    session_id: str
    client_id: str
    payer_type: str
    coinsurance_pct: float
    therapy_charge_cents: int
    materials_charge_cents: int
    billed_amount_cents: int
    allowed_amount_cents: int
    patient_responsibility_cents: int
    plan_paid_cents: int
    adjustment_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
