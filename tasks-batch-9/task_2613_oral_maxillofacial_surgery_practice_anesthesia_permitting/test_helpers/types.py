"""Domain types for the OMS Anesthesia Permitting API.

Entity TypedDicts, status enums and the operator-role enum, all named exactly
as the PRD names them.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PRACTICE_ADMINISTRATOR = "PracticeAdministrator"
    SCHEDULING_COORDINATOR = "SchedulingCoordinator"
    BENEFITS_SPECIALIST = "BenefitsSpecialist"
    INVENTORY_MANAGER = "InventoryManager"
    SURGEON = "Surgeon"
    ANESTHESIA_COORDINATOR = "AnesthesiaCoordinator"
    QUALITY_REVIEWER = "QualityReviewer"


class SedationPrivilegeState(str, Enum):
    UNPERMITTED = "UNPERMITTED"
    PERMITTED = "PERMITTED"
    RESTRICTED = "RESTRICTED"
    SUSPENDED = "SUSPENDED"


class PermitLevel(str, Enum):
    MINIMAL_SEDATION = "MINIMAL_SEDATION"
    MODERATE_SEDATION = "MODERATE_SEDATION"
    DEEP_SEDATION_GENERAL = "DEEP_SEDATION_GENERAL"


class PermitStatus(str, Enum):
    APPLIED = "APPLIED"
    INSPECTION_PENDING = "INSPECTION_PENDING"
    ACTIVE = "ACTIVE"
    PROBATION = "PROBATION"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class EnforcementReason(str, Enum):
    CRITICAL_DEFICIENCY = "CRITICAL_DEFICIENCY"
    DEFICIENCY_SCORE = "DEFICIENCY_SCORE"
    SENTINEL_EVENT = "SENTINEL_EVENT"
    DRILL_LAPSE = "DRILL_LAPSE"
    PERMIT_EXPIRY = "PERMIT_EXPIRY"


class InspectionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PASSED = "PASSED"
    FAILED_CORRECTABLE = "FAILED_CORRECTABLE"
    FAILED_CRITICAL = "FAILED_CRITICAL"


class DrillType(str, Enum):
    AIRWAY_OBSTRUCTION = "AIRWAY_OBSTRUCTION"
    LARYNGOSPASM = "LARYNGOSPASM"
    MALIGNANT_HYPERTHERMIA = "MALIGNANT_HYPERTHERMIA"
    CARDIAC_ARREST = "CARDIAC_ARREST"
    LOCAL_ANESTHETIC_TOXICITY = "LOCAL_ANESTHETIC_TOXICITY"


class StaffRoleType(str, Enum):
    SURGEON = "SURGEON"
    ANESTHESIA_MONITOR = "ANESTHESIA_MONITOR"
    RECOVERY_NURSE = "RECOVERY_NURSE"
    INVENTORY_TECH = "INVENTORY_TECH"


class BlockStatus(str, Enum):
    RESERVED = "RESERVED"
    PARTIALLY_RELEASED = "PARTIALLY_RELEASED"
    RELEASED = "RELEASED"


class AnesthesiaLevel(str, Enum):
    LOCAL_ONLY = "LOCAL_ONLY"
    MINIMAL_SEDATION = "MINIMAL_SEDATION"
    MODERATE_SEDATION = "MODERATE_SEDATION"
    DEEP_SEDATION_GENERAL = "DEEP_SEDATION_GENERAL"


class ProcedureCategory(str, Enum):
    THIRD_MOLAR = "THIRD_MOLAR"
    ORTHOGNATHIC = "ORTHOGNATHIC"
    PATHOLOGY = "PATHOLOGY"
    TRAUMA = "TRAUMA"
    IMPLANT = "IMPLANT"
    TMJ = "TMJ"


class SchedulingStatus(str, Enum):
    DRAFT = "DRAFT"
    BLOCK_HELD = "BLOCK_HELD"
    CONFIRMED = "CONFIRMED"
    IN_RECOVERY = "IN_RECOVERY"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ClearanceStatus(str, Enum):
    NOT_EVALUATED = "NOT_EVALUATED"
    EVALUATED = "EVALUATED"
    CLEARED = "CLEARED"
    DEFERRED = "DEFERRED"


class ReferralCoordinationStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    PENDING = "PENDING"
    ACKNOWLEDGED = "ACKNOWLEDGED"


class CancellationReason(str, Enum):
    PATIENT_REQUEST = "PATIENT_REQUEST"
    CLINICAL = "CLINICAL"
    PRIVILEGE_SUSPENDED = "PRIVILEGE_SUSPENDED"


class EvaluationStatus(str, Enum):
    DRAFT = "DRAFT"
    SIGNED = "SIGNED"
    VERIFIED = "VERIFIED"
    SUPERSEDED = "SUPERSEDED"
    VOIDED = "VOIDED"


class RiskBand(str, Enum):
    LOW = "LOW"
    ELEVATED = "ELEVATED"
    HIGH = "HIGH"
    PROHIBITIVE = "PROHIBITIVE"


class BenefitRoute(str, Enum):
    MEDICAL_PRIMARY = "MEDICAL_PRIMARY"
    DENTAL_PRIMARY = "DENTAL_PRIMARY"
    SPLIT = "SPLIT"
    SELF_PAY = "SELF_PAY"


class BenefitClass(str, Enum):
    MEDICAL = "MEDICAL"
    DENTAL = "DENTAL"


class DeterminationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    PENDED = "PENDED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class PendReason(str, Enum):
    MISSING_OP_REPORT = "MISSING_OP_REPORT"
    MEDICAL_NECESSITY_REVIEW = "MEDICAL_NECESSITY_REVIEW"
    COORDINATION_OF_BENEFITS = "COORDINATION_OF_BENEFITS"


class DenialReason(str, Enum):
    NOT_COVERED_BENEFIT = "NOT_COVERED_BENEFIT"
    EXCEEDS_ANNUAL_MAX = "EXCEEDS_ANNUAL_MAX"
    NO_MEDICAL_NECESSITY = "NO_MEDICAL_NECESSITY"


class LotStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    QUARANTINED = "QUARANTINED"


class SelectionMode(str, Enum):
    EXPLICIT = "EXPLICIT"
    AUTO_SIZED = "AUTO_SIZED"


class ReservationStatus(str, Enum):
    HELD = "HELD"
    CONSUMED = "CONSUMED"
    RELEASED = "RELEASED"
    SHORTED = "SHORTED"


class AdverseEventType(str, Enum):
    AIRWAY_OBSTRUCTION = "AIRWAY_OBSTRUCTION"
    HYPOXEMIA = "HYPOXEMIA"
    PROLONGED_RECOVERY = "PROLONGED_RECOVERY"
    UNPLANNED_INTUBATION = "UNPLANNED_INTUBATION"
    NERVE_INJURY = "NERVE_INJURY"
    DEATH = "DEATH"


class AdverseEventSeverity(str, Enum):
    MINOR = "MINOR"
    MODERATE = "MODERATE"
    SEVERE = "SEVERE"
    SENTINEL = "SENTINEL"


class AdverseEventStatus(str, Enum):
    REPORTED = "REPORTED"
    UNDER_MORBIDITY_REVIEW = "UNDER_MORBIDITY_REVIEW"
    REVIEW_SIGNED_OFF = "REVIEW_SIGNED_OFF"
    CLOSED = "CLOSED"


class Modality(str, Enum):
    PANORAMIC = "PANORAMIC"
    CEPHALOMETRIC = "CEPHALOMETRIC"
    CBCT_SMALL_FOV = "CBCT_SMALL_FOV"
    CBCT_LARGE_FOV = "CBCT_LARGE_FOV"


class JustificationCode(str, Enum):
    IMPLANT_PLANNING = "IMPLANT_PLANNING"
    THIRD_MOLAR_ASSESSMENT = "THIRD_MOLAR_ASSESSMENT"
    PATHOLOGY_STAGING = "PATHOLOGY_STAGING"
    TRAUMA_SURVEY = "TRAUMA_SURVEY"
    ORTHOGNATHIC_PLANNING = "ORTHOGNATHIC_PLANNING"


class DoseFlag(str, Enum):
    WITHIN_PROTOCOL = "WITHIN_PROTOCOL"
    ABOVE_REFERENCE_LEVEL = "ABOVE_REFERENCE_LEVEL"


# --- Entity shapes -----------------------------------------------------------
# Mutable resources carry id, created_at, updated_at and version.
# EmergencyDrill and ImagingStudy are write-once and carry only id + created_at.

class Practice(TypedDict):
    id: str
    name: str
    state_code: str
    recovery_bay_count: int
    turnover_buffer_minutes: int
    consignment_credit_limit_cents: int
    sedation_privilege_state: str
    open_adverse_event_count: int
    consignment_committed_cents: int
    created_at: str
    updated_at: str
    version: int


class AnesthesiaPermit(TypedDict):
    id: str
    practice_id: str
    permit_level: str
    applied_on: str
    status: str
    issued_at: Optional[str]
    expires_at: Optional[str]
    required_drill_types: List[str]
    drill_compliance_ratio: float
    probation_count: int
    remediation_deadline_at: Optional[str]
    last_enforcement_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FacilityInspection(TypedDict):
    id: str
    permit_id: str
    scheduled_for: str
    status: str
    minor_deficiency_count: int
    major_deficiency_count: int
    critical_deficiency_count: int
    inspection_score: Optional[int]
    outcome_recorded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EmergencyDrill(TypedDict):
    id: str
    practice_id: str
    drill_type: str
    conducted_at: str
    participant_staff_ids: List[str]
    deficiency_noted: bool
    created_at: str


class StaffMember(TypedDict):
    id: str
    practice_id: str
    full_name: str
    role_type: str
    monitoring_certified: bool
    acls_expires_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Patient(TypedDict):
    id: str
    practice_id: str
    full_name: str
    date_of_birth: str
    asa_class: int
    airway_class: int
    weight_kg: float
    medical_plan_active: bool
    dental_plan_active: bool
    dental_annual_remaining_cents: int
    age_years: int
    created_at: str
    updated_at: str
    version: int


class BlockTime(TypedDict):
    id: str
    practice_id: str
    surgeon_id: str
    room_code: str
    block_start: str
    block_end: str
    release_deadline_hours: int
    status: str
    block_duration_minutes: int
    committed_minutes: int
    released_minutes: int
    open_minutes: int
    utilization_pct: float
    created_at: str
    updated_at: str
    version: int


class SurgicalCase(TypedDict):
    id: str
    practice_id: str
    patient_id: str
    primary_surgeon_id: str
    monitor_staff_id: Optional[str]
    block_id: Optional[str]
    prerequisite_case_id: Optional[str]
    procedure_category: str
    planned_anesthesia_level: str
    planned_start: str
    planned_end: str
    total_charge_cents: int
    referring_provider_npi: Optional[str]
    duration_minutes: int
    scheduling_status: str
    clearance_status: str
    referral_coordination_status: str
    recovery_minutes_required: int
    recovery_started_at: Optional[str]
    cancellation_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PreAnesthesiaEvaluation(TypedDict):
    id: str
    case_id: str
    evaluator_staff_id: str
    asa_class_recorded: int
    airway_class_recorded: int
    comorbidity_count: int
    status: str
    provisional_risk_score: Optional[float]
    final_risk_score: Optional[float]
    risk_band: Optional[str]
    fasting_solids_last_at: Optional[str]
    fasting_clears_last_at: Optional[str]
    npo_solids_minutes: Optional[int]
    npo_clears_minutes: Optional[int]
    escort_confirmed: bool
    escort_name: Optional[str]
    signed_at: Optional[str]
    verified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BenefitDetermination(TypedDict):
    id: str
    case_id: str
    service_lines: List[dict]
    route: str
    primary_payer: Optional[str]
    status: str
    submission_count: int
    medical_allowed_cents: int
    dental_allowed_cents: int
    patient_responsibility_cents: int
    dental_annual_remaining_snapshot_cents: int
    pend_reason: Optional[str]
    denial_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ImplantLot(TypedDict):
    id: str
    practice_id: str
    manufacturer_code: str
    catalog_reference: str
    diameter_mm: float
    length_mm: float
    is_consignment: bool
    unit_cost_cents: int
    quantity_on_hand: int
    expiry_date: str
    quantity_reserved: int
    available_quantity: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ImplantReservation(TypedDict):
    id: str
    case_id: str
    lot_id: str
    quantity: int
    requested_diameter_mm: Optional[float]
    requested_length_mm: Optional[float]
    selection_mode: str
    status: str
    line_subtotal_cents: int
    restocking_fee_cents: int
    consignment_credit_cents: int
    consignment_liability_cents: int
    created_at: str
    updated_at: str
    version: int


class AdverseEvent(TypedDict):
    id: str
    case_id: str
    reviewer_staff_id: Optional[str]
    event_type: str
    severity: str
    occurred_at: str
    narrative: str
    reported_at: str
    reporting_deadline_at: str
    late_report: bool
    status: str
    regulator_notified: bool
    corrective_action_required: Optional[bool]
    created_at: str
    updated_at: str
    version: int


class ImagingStudy(TypedDict):
    id: str
    patient_id: str
    case_id: Optional[str]
    modality: str
    justification_code: str
    acquired_at: str
    dose_mgy_cm2: float
    dose_flag: str
    retention_until: str
    created_at: str
