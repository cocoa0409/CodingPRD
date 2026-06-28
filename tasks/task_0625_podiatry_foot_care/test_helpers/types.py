"""Domain types: entity TypedDicts, status enums, role enum (Podiatry Foot-Care API)."""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Role enum ────────────────────────────────────────────────────────────
class UserRole(str, Enum):
    PRACTICE_ADMIN = "PracticeAdmin"
    PODIATRIST = "Podiatrist"
    BILLING_SPECIALIST = "BillingSpecialist"
    FRONT_DESK = "FrontDesk"
    PAYER_AGENT = "PayerAgent"


# ─── Status enums (one per entity with a lifecycle) ───────────────────────
class EncounterStatus(str, Enum):
    OPEN = "OPEN"
    EXAM_DONE = "EXAM_DONE"
    CODED = "CODED"
    SUBMITTED = "SUBMITTED"
    ADJUDICATED = "ADJUDICATED"
    VOIDED = "VOIDED"


class PriorAuthorizationStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    EXHAUSTED = "EXHAUSTED"
    EXPIRED = "EXPIRED"


class OrthoticRxStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_PA = "PENDING_PA"
    APPROVED = "APPROVED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class LabOrderStatus(str, Enum):
    QUEUED = "QUEUED"
    SHIPPED = "SHIPPED"
    RECEIVED = "RECEIVED"
    CANCELLED = "CANCELLED"


class DmeDispenseStatus(str, Enum):
    DISPENSED = "DISPENSED"
    RETURNED = "RETURNED"


class ImagingOrderStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class RecallScheduleStatus(str, Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


# ─── Value enums ──────────────────────────────────────────────────────────
class ProviderRoleType(str, Enum):
    PODIATRIST = "PODIATRIST"
    NP_PA = "NP_PA"


class ModalityType(str, Enum):
    XRAY = "XRAY"
    ULTRASOUND = "ULTRASOUND"
    MRI = "MRI"


class ServiceCategory(str, Enum):
    DME = "DME"
    ORTHOTIC = "ORTHOTIC"
    IMAGING = "IMAGING"


class ProcedureKind(str, Enum):
    ROUTINE_NAIL_DEBRIDEMENT = "ROUTINE_NAIL_DEBRIDEMENT"
    ROUTINE_CALLUS_PARING = "ROUTINE_CALLUS_PARING"
    WOUND_DEBRIDEMENT = "WOUND_DEBRIDEMENT"
    NAIL_AVULSION = "NAIL_AVULSION"


class CoverageDecision(str, Enum):
    PENDING = "PENDING"
    COVERED = "COVERED"
    DENIED_FREQUENCY = "DENIED_FREQUENCY"
    DENIED_NO_QUALIFYING_DX = "DENIED_NO_QUALIFYING_DX"


class AcquisitionMode(str, Enum):
    PURCHASE = "PURCHASE"
    RENTAL = "RENTAL"


class FootSide(str, Enum):
    LEFT = "LEFT"
    RIGHT = "RIGHT"
    BILATERAL = "BILATERAL"


class Specialty(str, Enum):
    VASCULAR = "VASCULAR"
    ENDOCRINOLOGY = "ENDOCRINOLOGY"
    ORTHOPEDIC_SURGERY = "ORTHOPEDIC_SURGERY"
    WOUND_CARE = "WOUND_CARE"


# ─── Entity TypedDicts (all thirteen carry id/created_at/updated_at/version) ─
class Practice(TypedDict):
    id: str
    name: str
    npi: str
    routine_care_min_interval_days: int
    fee_split_medicare_pct: float
    created_at: str
    updated_at: str
    version: int


class Provider(TypedDict):
    id: str
    practice_id: str
    full_name: str
    role_type: str
    is_active: bool
    created_at: str
    updated_at: str
    version: int


class Modality(TypedDict):
    id: str
    practice_id: str
    name: str
    modality_type: str
    cleanup_buffer_minutes: int
    created_at: str
    updated_at: str
    version: int


class Patient(TypedDict):
    id: str
    practice_id: str
    full_name: str
    date_of_birth: str
    has_diabetes_mellitus: bool
    has_loss_protective_sensation: bool
    has_peripheral_arterial_disease: bool
    has_foot_deformity: bool
    has_prior_ulcer_or_amputation: bool
    diabetic_foot_risk_category: int
    last_covered_routine_care_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PriorAuthorization(TypedDict):
    id: str
    patient_id: str
    service_category: str
    hcpcs_code: str
    authorized_units: int
    units_consumed: int
    remaining_units: int
    valid_from_date: str
    valid_through_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Encounter(TypedDict):
    id: str
    patient_id: str
    provider_id: str
    scheduled_start: str
    scheduled_end: str
    exam_billed_cents: int
    exam_fee_cap_cents: int
    exam_coverage_decision: str
    total_medicare_pays_cents: int
    total_patient_resp_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Procedure(TypedDict):
    id: str
    encounter_id: str
    patient_id: str
    procedure_kind: str
    service_date: str
    billed_cents: int
    fee_cap_cents: int
    coverage_decision: str
    medicare_pays_cents: int
    patient_resp_cents: int
    is_routine: bool
    created_at: str
    updated_at: str
    version: int


class OrthoticRx(TypedDict):
    id: str
    encounter_id: str
    patient_id: str
    prior_authorization_id: str
    l_code: str
    foot_side: str
    status: str
    created_at: str
    updated_at: str
    version: int


class LabOrder(TypedDict):
    id: str
    orthotic_rx_id: str
    lab_name: str
    line_items: List[dict]
    total_cents: int
    units_drawn: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DmeDispense(TypedDict):
    id: str
    prior_authorization_id: str
    encounter_id: str
    patient_id: str
    hcpcs_code: str
    acquisition_mode: str
    units: int
    purchase_price_cents: int
    monthly_rental_cents: Optional[int]
    cumulative_rental_paid_cents: int
    this_period_charge_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ImagingOrder(TypedDict):
    id: str
    encounter_id: str
    patient_id: str
    modality_id: str
    study_start: str
    study_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Referral(TypedDict):
    id: str
    encounter_id: str
    patient_id: str
    specialty: str
    reason: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RecallSchedule(TypedDict):
    id: str
    patient_id: str
    anchor_date: str
    interval_days: int
    due_date: str
    status: str
    created_at: str
    updated_at: str
    version: int
