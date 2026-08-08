"""Domain types: entity TypedDicts, status enums, and the role enum.

All names mirror the field and status vocabulary of the Women's Health &
Menopause Telehealth API exactly as described in the PRD.
"""
from enum import Enum
from typing import TypedDict, Optional, List, Dict, Any


# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    PATIENT = "Patient"
    PROVIDER = "Provider"
    BILLING_ADMIN = "BillingAdmin"
    CARE_COORDINATOR = "CareCoordinator"


# --------------------------------------------------------------------------
# Status enums
# --------------------------------------------------------------------------
class IntakeStatus(str, Enum):
    DRAFT = "DRAFT"
    CLEARED = "CLEARED"
    FLAGGED = "FLAGGED"


class VisitStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class PrescriptionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DISCONTINUED = "DISCONTINUED"
    EXPIRED = "EXPIRED"


class LabOrderStatus(str, Enum):
    PENDING = "PENDING"
    REVIEWED = "REVIEWED"
    CANCELLED = "CANCELLED"


class RefillStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    FULFILLED = "FULFILLED"
    REVERSED = "REVERSED"


class SubscriptionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAST_DUE = "PAST_DUE"
    CANCELLED = "CANCELLED"
    SUPERSEDED = "SUPERSEDED"


class ChargeStatus(str, Enum):
    ESTIMATED = "ESTIMATED"
    ADJUDICATED = "ADJUDICATED"
    VOID = "VOID"
    REVERSED = "REVERSED"


class AdherenceStatus(str, Enum):
    NON_ADHERENT = "NON_ADHERENT"
    AT_RISK = "AT_RISK"
    ADHERENT = "ADHERENT"


class BillingMode(str, Enum):
    CASH = "CASH"
    INSURANCE = "INSURANCE"


class MenopauseStage(str, Enum):
    PERIMENOPAUSE = "PERIMENOPAUSE"
    MENOPAUSE = "MENOPAUSE"
    POSTMENOPAUSE = "POSTMENOPAUSE"
    UNKNOWN = "UNKNOWN"


class HrtType(str, Enum):
    ESTROGEN_PATCH = "ESTROGEN_PATCH"
    ESTROGEN_ORAL = "ESTROGEN_ORAL"
    PROGESTERONE = "PROGESTERONE"
    COMBINED = "COMBINED"
    VAGINAL_ESTROGEN = "VAGINAL_ESTROGEN"


class Specialty(str, Enum):
    GYNECOLOGY = "GYNECOLOGY"
    ENDOCRINOLOGY = "ENDOCRINOLOGY"
    FAMILY_MEDICINE = "FAMILY_MEDICINE"


class PlanTier(str, Enum):
    ESSENTIAL = "ESSENTIAL"
    PLUS = "PLUS"


class MessageType(str, Enum):
    GENERAL = "GENERAL"
    ADHERENCE_OUTREACH = "ADHERENCE_OUTREACH"
    SUSPENSION_NOTICE = "SUSPENSION_NOTICE"
    DENIAL_NOTICE = "DENIAL_NOTICE"


class AuthorKind(str, Enum):
    PATIENT = "PATIENT"
    PROVIDER = "PROVIDER"
    CARE_COORDINATOR = "CARE_COORDINATOR"
    SYSTEM = "SYSTEM"


# --------------------------------------------------------------------------
# Entity TypedDicts (common_fields: true carries id/created_at/updated_at/version)
# --------------------------------------------------------------------------
class Patient(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    date_of_birth: str
    state_code: str
    billing_mode: str
    menopause_stage: str
    created_at: str
    updated_at: str
    version: int


class Provider(TypedDict, total=False):
    id: str
    full_name: str
    specialty: str
    npi: str
    visit_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class InsurancePolicy(TypedDict, total=False):
    id: str
    patient_id: str
    payer_name: str
    deductible_cents: int
    remaining_deductible_cents: int
    consumed_deductible_cents: int
    coinsurance_rate: float
    out_of_pocket_max_cents: int
    oop_accumulated_cents: int
    created_at: str
    updated_at: str
    version: int


class IntakeAssessment(TypedDict, total=False):
    id: str
    patient_id: str
    symptom_ratings: List[Dict[str, Any]]
    reported_conditions: List[str]
    symptom_severity_score: float
    has_absolute_contraindication: bool
    submitted_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Visit(TypedDict, total=False):
    id: str
    patient_id: str
    provider_id: str
    intake_assessment_id: str
    scheduled_start: str
    scheduled_end: str
    visit_charge_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Prescription(TypedDict, total=False):
    id: str
    patient_id: str
    provider_id: str
    visit_id: str
    care_plan_id: str
    hrt_type: str
    days_supply_per_fill: int
    total_refills_authorized: int
    refills_remaining: int
    lab_required_before_refill: bool
    coverage_days: int
    coverage_start_date: str
    coverage_end_date: str
    last_fill_date: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class LabOrder(TypedDict, total=False):
    id: str
    prescription_id: str
    panel_type: str
    result: Optional[str]
    resulted_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Refill(TypedDict, total=False):
    id: str
    prescription_id: str
    days_supply: int
    fill_date: Optional[str]
    charge_id: Optional[str]
    denial_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict, total=False):
    id: str
    patient_id: str
    plan_tier: str
    monthly_fee_cents: int
    started_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Charge(TypedDict, total=False):
    id: str
    patient_id: str
    billable_kind: str
    billable_id: str
    insurance_policy_id: Optional[str]
    billing_mode: str
    allowed_amount_cents: int
    estimated_patient_responsibility_cents: int
    final_patient_responsibility_cents: Optional[int]
    insurance_paid_cents: Optional[int]
    deductible_applied_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class CarePlan(TypedDict, total=False):
    id: str
    patient_id: str
    prescription_id: str
    realized_pdc: float
    projected_pdc: float
    adherence_status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only event log: carries ONLY id + created_at.
class CarePlanMessage(TypedDict, total=False):
    id: str
    care_plan_id: str
    author_kind: str
    message_type: str
    body: str
    created_at: str
