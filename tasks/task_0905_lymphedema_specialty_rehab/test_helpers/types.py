"""Domain types: entity TypedDicts, status enums, and the role enum.

All names use the terminology of the Lymphedema & Specialty Rehab API contract.
"""
from enum import Enum
from typing import TypedDict, List, Optional


# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    CLINICIAN = "Clinician"
    AUTHORIZER = "Authorizer"
    DME_COORDINATOR = "DMECoordinator"
    CLINIC_ADMIN = "ClinicAdmin"


# --------------------------------------------------------------------------
# Status enums
# --------------------------------------------------------------------------
class PatientStatus(str, Enum):
    ACTIVE = "ACTIVE"


class EvaluationStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    SUPERSEDED = "SUPERSEDED"


class AuthorizationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    EXHAUSTED = "EXHAUSTED"


class TreatmentPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    ON_HOLD = "ON_HOLD"
    COMPLETED = "COMPLETED"


class TreatmentPlanPhase(str, Enum):
    PHASE_1_INTENSIVE = "PHASE_1_INTENSIVE"
    PHASE_2_MAINTENANCE = "PHASE_2_MAINTENANCE"


class TherapistStatus(str, Enum):
    ACTIVE = "ACTIVE"


class TherapistCredential(str, Enum):
    CLT = "CLT"
    OT = "OT"
    PT = "PT"


class SessionClinicalStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class SessionBillingStatus(str, Enum):
    RESERVED = "RESERVED"
    BILLED = "BILLED"
    VOID = "VOID"


class CdtComponent(str, Enum):
    MLD = "MLD"
    COMPRESSION_BANDAGING = "COMPRESSION_BANDAGING"
    EXERCISE = "EXERCISE"
    SKIN_CARE = "SKIN_CARE"
    EDUCATION = "EDUCATION"


class GarmentOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    SUPERSEDED = "SUPERSEDED"


class CompressionClass(str, Enum):
    CLASS_1 = "CLASS_1"
    CLASS_2 = "CLASS_2"
    CLASS_3 = "CLASS_3"
    CLASS_4 = "CLASS_4"


class GarmentType(str, Enum):
    SLEEVE = "SLEEVE"
    STOCKING = "STOCKING"
    CHIN_STRAP = "CHIN_STRAP"
    VEST = "VEST"
    COMPRESSION_SHORT = "COMPRESSION_SHORT"


class DispenseStatus(str, Enum):
    DISPENSED = "DISPENSED"
    RETURNED = "RETURNED"


class ReassessmentStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"


class OutcomeCategory(str, Enum):
    EXCELLENT = "EXCELLENT"
    GOOD = "GOOD"
    PARTIAL = "PARTIAL"
    REGRESSION = "REGRESSION"


class BodyRegion(str, Enum):
    LEFT_ARM = "LEFT_ARM"
    RIGHT_ARM = "RIGHT_ARM"
    LEFT_LEG = "LEFT_LEG"
    RIGHT_LEG = "RIGHT_LEG"
    HEAD_NECK = "HEAD_NECK"
    TRUNK = "TRUNK"
    GENITAL = "GENITAL"


class Etiology(str, Enum):
    PRIMARY = "PRIMARY"
    SECONDARY = "SECONDARY"


class IslStage(str, Enum):
    STAGE_0 = "STAGE_0"
    STAGE_I = "STAGE_I"
    STAGE_II = "STAGE_II"
    STAGE_III = "STAGE_III"


# --------------------------------------------------------------------------
# Entity TypedDicts
# --------------------------------------------------------------------------
# common_fields: true -> id, created_at, updated_at, version
class Patient(TypedDict):
    id: str
    full_name: str
    mrn: str
    date_of_birth: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Evaluation(TypedDict):
    id: str
    patient_id: str
    body_region: str
    etiology: str
    isl_stage: str
    interval_cm: float
    circumferences_cm: List[float]
    contralateral_circumferences_cm: List[float]
    limb_volume_ml: float
    contralateral_volume_ml: float
    excess_volume_ml: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Authorization(TypedDict):
    id: str
    patient_id: str
    body_region: str
    payer_name: str
    auth_number: str
    visit_cap: int
    effective_start_date: str
    effective_end_date: str
    visits_reserved: int
    visits_used: int
    visits_remaining: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TreatmentPlan(TypedDict):
    id: str
    patient_id: str
    evaluation_id: str
    authorization_id: str
    prescribed_daily_minutes: int
    phase: str
    adherence_rate: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Therapist(TypedDict):
    id: str
    full_name: str
    credential: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Session(TypedDict):
    id: str
    plan_id: str
    authorization_id: str
    therapist_id: str
    scheduled_start: str
    scheduled_end: str
    cdt_component: str
    clinical_status: str
    billing_status: str
    created_at: str
    updated_at: str
    version: int


class GarmentOrder(TypedDict):
    id: str
    patient_id: str
    evaluation_id: str
    body_region: str
    quantity: int
    garment_type: str
    compression_class: str
    l_code: str
    custom_fabrication: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class DMEItem(TypedDict):
    id: str
    sku: str
    description: Optional[str]
    l_code: str
    initial_stock_qty: int
    outstanding_dispensed_qty: int
    on_hand_qty: int
    created_at: str
    updated_at: str
    version: int


class Dispense(TypedDict):
    id: str
    garment_order_id: str
    dme_item_id: str
    quantity: int
    l_code: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Reassessment(TypedDict):
    id: str
    plan_id: str
    baseline_evaluation_id: str
    current_evaluation_id: str
    volume_reduction_pct: float
    perv_pct: float
    outcome_category: str
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false -> append-only, only id + created_at (no updated_at / version)
class AdherenceLog(TypedDict):
    id: str
    plan_id: str
    log_date: str
    minutes_completed: int
    wore_garment: bool
    created_at: str
