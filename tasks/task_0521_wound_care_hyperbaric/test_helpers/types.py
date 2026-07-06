"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, List, Optional


# --- Role enum ---

class UserRole(str, Enum):
    INTAKE_COORDINATOR = "IntakeCoordinator"
    WOUND_CLINICIAN = "WoundClinician"
    HYPERBARIC_TECH = "HyperbaricTech"
    PAYER_LIAISON = "PayerLiaison"
    ATTENDING_PHYSICIAN = "AttendingPhysician"


# --- Status enums ---

class PatientStatus(str, Enum):
    INTAKE = "INTAKE"
    IN_CARE = "IN_CARE"
    DISCHARGED = "DISCHARGED"
    TRANSFERRED = "TRANSFERRED"


class ReferralStatus(str, Enum):
    RECEIVED = "RECEIVED"
    NEEDS_INFO = "NEEDS_INFO"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"


class TreatmentPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    HEALED = "HEALED"
    CLOSED = "CLOSED"


class CoverageStatus(str, Enum):
    PENDING = "PENDING"
    COVERED = "COVERED"
    NOT_COVERED = "NOT_COVERED"


class PriorAuthorizationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ADDITIONAL_INFO_REQUESTED = "ADDITIONAL_INFO_REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class DebridementProcedureStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class HboSessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class SupplyOrderStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class AcuteTransferStatus(str, Enum):
    INITIATED = "INITIATED"
    ACCEPTED = "ACCEPTED"
    CANCELLED = "CANCELLED"


class OutcomeReportStatus(str, Enum):
    FINAL = "FINAL"


# --- Field enums ---

class RoleKind(str, Enum):
    WOUND = "WOUND"
    HYPERBARIC = "HYPERBARIC"
    ATTENDING = "ATTENDING"


class WoundStage(str, Enum):
    STAGE_1 = "STAGE_1"
    STAGE_2 = "STAGE_2"
    STAGE_3 = "STAGE_3"
    STAGE_4 = "STAGE_4"
    UNSTAGEABLE = "UNSTAGEABLE"


class TissueType(str, Enum):
    GRANULATION = "GRANULATION"
    EPITHELIAL = "EPITHELIAL"
    SLOUGH = "SLOUGH"
    NECROTIC = "NECROTIC"


class SupplyKind(str, Enum):
    ADVANCED_DRESSING = "ADVANCED_DRESSING"
    SKIN_GRAFT = "SKIN_GRAFT"


# --- Entity TypedDicts (common_fields: true carry id/created_at/updated_at/version) ---

class Center(TypedDict):
    id: str
    name: str
    current_utc: str
    created_at: str
    updated_at: str
    version: int


class Clinician(TypedDict):
    id: str
    center_id: str
    name: str
    role_kind: str
    active: bool
    created_at: str
    updated_at: str
    version: int


class Chamber(TypedDict):
    id: str
    center_id: str
    label: str
    turnover_buffer_minutes: int
    occupied_slot_count: int
    created_at: str
    updated_at: str
    version: int


class PayerPolicy(TypedDict):
    id: str
    center_id: str
    payer_name: str
    requires_prior_auth: bool
    max_covered_hbo_sessions: int
    per_session_cents: int
    min_healing_pct_threshold: float
    created_at: str
    updated_at: str
    version: int


class Patient(TypedDict):
    id: str
    center_id: str
    mrn: str
    full_name: str
    payer_policy_id: str
    latest_wound_area_cm2: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Referral(TypedDict):
    id: str
    patient_id: str
    source_provider: str
    reason: str
    status: str
    created_at: str
    updated_at: str
    version: int


# WoundAssessment: common_fields false — append-only, id + created_at only
class WoundAssessment(TypedDict):
    id: str
    patient_id: str
    assessed_at: str
    stage: str
    length_cm: float
    width_cm: float
    tissue_type: str
    infected: bool
    area_cm2: float
    severity_score: int
    created_at: str


class TreatmentPlan(TypedDict):
    id: str
    patient_id: str
    baseline_assessment_id: str
    coverage_status: str
    provisional_covered_cents: int
    provisional_hbo_covered_cents: int
    finalized_hbo_covered_cents: int
    debridement_supply_budget_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PriorAuthorization(TypedDict):
    id: str
    treatment_plan_id: str
    requested_hbo_sessions: int
    clinical_justification: str
    info_request_note: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DebridementProcedure(TypedDict):
    id: str
    treatment_plan_id: str
    clinician_id: str
    window_start: str
    window_end: str
    performed_by_user_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class HboSession(TypedDict):
    id: str
    treatment_plan_id: str
    chamber_id: str
    window_start: str
    window_end: str
    treatment_pressure_ata: float
    dive_log_entries: list
    status: str
    created_at: str
    updated_at: str
    version: int


class SupplyOrder(TypedDict):
    id: str
    treatment_plan_id: str
    supply_kind: str
    line_items: list
    covered_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# PhotoDocument: common_fields false — append-only, id + created_at only
class PhotoDocument(TypedDict):
    id: str
    wound_assessment_id: str
    patient_id: str
    image_uri: str
    captured_at: str
    created_at: str


class AcuteTransfer(TypedDict):
    id: str
    patient_id: str
    destination_facility: str
    clinical_reason: str
    initiated_by_user_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class OutcomeReport(TypedDict):
    id: str
    treatment_plan_id: str
    actual_healing_pct: float
    projected_healing_pct: float
    finalized_hbo_covered_cents: int
    meets_coverage_threshold: bool
    status: str
    created_at: str
    updated_at: str
    version: int
