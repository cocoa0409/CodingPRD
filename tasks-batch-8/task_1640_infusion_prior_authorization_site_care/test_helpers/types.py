"""Domain types: entity TypedDicts, status enums, role enum.

All field names follow the PRD exactly. Per the PRD common-resource-properties
section, every resource carries id + created_at + updated_at + version — no
resource in this domain omits updated_at or version.
"""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    POLICY_ADMIN = "PolicyAdmin"
    AUTH_COORDINATOR = "AuthCoordinator"
    MEDICAL_DIRECTOR = "MedicalDirector"
    FINANCE_SPECIALIST = "FinanceSpecialist"
    SCHEDULER = "Scheduler"


class BenefitChannel(str, Enum):
    MEDICAL = "MEDICAL"
    PHARMACY = "PHARMACY"
    EITHER = "EITHER"


class SitePolicy(str, Enum):
    NO_STEERING = "NO_STEERING"
    STEER_TO_HOME = "STEER_TO_HOME"
    STEER_TO_OFFICE = "STEER_TO_OFFICE"


class SiteType(str, Enum):
    HOME = "HOME"
    OFFICE = "OFFICE"
    HOSPITAL_OUTPATIENT = "HOSPITAL_OUTPATIENT"


class AuthorizationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    PENDED = "PENDED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"
    DENIED_CLOSED = "DENIED_CLOSED"


class CriteriaStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class AppealStatus(str, Enum):
    LEVEL_1 = "LEVEL_1"
    LEVEL_1_DECIDED = "LEVEL_1_DECIDED"
    LEVEL_2 = "LEVEL_2"
    LEVEL_2_DECIDED = "LEVEL_2_DECIDED"
    EXTERNAL_REVIEW = "EXTERNAL_REVIEW"
    CLOSED_UPHELD = "CLOSED_UPHELD"
    CLOSED_OVERTURNED = "CLOSED_OVERTURNED"


class AppealOutcome(str, Enum):
    UPHELD = "UPHELD"
    OVERTURNED = "OVERTURNED"


class PeerToPeerStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    NO_SHOW = "NO_SHOW"
    COMPLETED = "COMPLETED"


class PeerToPeerOutcome(str, Enum):
    UPHOLD = "UPHOLD"
    OVERTURN = "OVERTURN"


class ScoreVariant(str, Enum):
    COST_RATIO = "COST_RATIO"
    TRAVEL_BURDEN = "TRAVEL_BURDEN"


class BenefitInvestigationStatus(str, Enum):
    INITIATED = "INITIATED"
    VERIFIED = "VERIFIED"


class DeterminedChannel(str, Enum):
    MEDICAL = "MEDICAL"
    PHARMACY = "PHARMACY"


class Routing(str, Enum):
    BUY_AND_BILL = "BUY_AND_BILL"
    SPECIALTY_PHARMACY = "SPECIALTY_PHARMACY"


class ClearanceMethod(str, Enum):
    ACCUMULATOR_METHOD = "ACCUMULATOR_METHOD"
    BILLED_CHARGES_METHOD = "BILLED_CHARGES_METHOD"


class ClearanceStatus(str, Enum):
    ESTIMATED = "ESTIMATED"
    CLEARED = "CLEARED"
    ON_HOLD = "ON_HOLD"


class LineItemStatus(str, Enum):
    ACTIVE = "ACTIVE"
    VOIDED = "VOIDED"


class AppointmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    MISSED = "MISSED"


class DoseChangeStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class DeterminationOutcome(str, Enum):
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    PENDED = "PENDED"


class PayerPolicy(TypedDict, total=False):
    id: str
    payer_code: str
    drug_code: str
    regimen_name: str
    requires_prior_auth: bool
    benefit_channel: str
    buy_and_bill_required: bool
    validity_days: int
    pharmacy_validity_days: int
    max_course_days: int
    max_dose_mg: int
    allowed_amount_known: bool
    discount_rate: float
    site_policy: str
    steer_threshold: float
    deductible_cents: int
    coinsurance_pct: float
    oop_max_cents: int
    prepay_limit_cents: int
    created_at: str
    updated_at: str
    version: int


class Patient(TypedDict, total=False):
    id: str
    member_id: str
    full_name: str
    diagnosis_code: str
    payer_code: str
    plan_year_end: str
    deductible_remaining_cents: int
    oop_remaining_cents: int
    rural_resident: bool
    travel_minutes_to_hospital: int
    created_at: str
    updated_at: str
    version: int


class AuthorizationRequest(TypedDict, total=False):
    id: str
    patient_id: str
    policy_id: str
    requested_site_type: str
    requested_dose_mg: int
    patient_weight_kg: float
    supersedes_request_id: Optional[str]
    status: str
    submitted_at: Optional[str]
    pended_at: Optional[str]
    denied_at: Optional[str]
    appeal_deadline: Optional[str]
    auth_valid_from: Optional[str]
    auth_valid_to: Optional[str]
    approved_dose_mg: Optional[int]
    denial_reason: Optional[str]
    created_by_user_id: str
    decided_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ClinicalCriteriaSubmission(TypedDict, total=False):
    id: str
    authorization_request_id: str
    criterion_code: str
    response_value: str
    status: str
    created_by_user_id: str
    reviewed_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Appeal(TypedDict, total=False):
    id: str
    authorization_request_id: str
    reason: str
    status: str
    decided_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PeerToPeerReview(TypedDict, total=False):
    id: str
    appeal_id: str
    reviewer_user_id: str
    scheduled_start: str
    scheduled_end: str
    status: str
    reschedule_count: int
    outcome: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SiteOfCareDetermination(TypedDict, total=False):
    id: str
    authorization_request_id: str
    home_allowed_cents: int
    hospital_allowed_cents: int
    home_billed_cents: int
    hospital_billed_cents: int
    score_variant: str
    steer_score: float
    recommended_site_type: str
    steered: bool
    created_at: str
    updated_at: str
    version: int


class BenefitInvestigation(TypedDict, total=False):
    id: str
    authorization_request_id: str
    status: str
    determined_channel: Optional[str]
    routing: Optional[str]
    verified_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FinancialClearance(TypedDict, total=False):
    id: str
    authorization_request_id: str
    method: str
    status: str
    estimated_patient_responsibility_cents: int
    estimated_by_user_id: str
    cleared_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ResponsibilityLineItem(TypedDict, total=False):
    id: str
    financial_clearance_id: str
    description: str
    allowed_amount_cents: int
    billed_charges_cents: int
    patient_share_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class InfusionChair(TypedDict, total=False):
    id: str
    site_type: str
    label: str
    turnover_buffer_minutes: int
    created_at: str
    updated_at: str
    version: int


class InfusionAppointment(TypedDict, total=False):
    id: str
    authorization_request_id: str
    chair_id: str
    scheduled_start: str
    scheduled_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DoseChangeRequest(TypedDict, total=False):
    id: str
    authorization_request_id: str
    new_dose_mg: int
    delta_pct: float
    reauth_required: bool
    status: str
    decided_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int
