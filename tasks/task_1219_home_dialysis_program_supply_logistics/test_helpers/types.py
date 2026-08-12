"""Domain types: entity TypedDicts, status enums, role enum.

All entities carry common fields (id, created_at, updated_at, version) per
PRD section 2.4 (Common Resource Properties).
"""
from enum import Enum
from typing import TypedDict, Optional, List, Any


# --------------------------------------------------------------------- roles
class UserRole(str, Enum):
    PATIENT = "Patient"
    HOME_NURSE = "HomeNurse"
    NEPHROLOGIST = "Nephrologist"
    SUPPLY_COORDINATOR = "SupplyCoordinator"
    BIOMED_TECHNICIAN = "BiomedTechnician"
    PROGRAM_ADMIN = "ProgramAdmin"


# ------------------------------------------------------------- enum domains
class ProgramStatus(str, Enum):
    TRAINING = "TRAINING"
    ACTIVE_HOME = "ACTIVE_HOME"
    SUSPENDED = "SUSPENDED"
    TRANSITIONED_OUT = "TRANSITIONED_OUT"


class Posture(str, Enum):
    NOT_READY = "NOT_READY"
    HOME_READY = "HOME_READY"
    AT_RISK = "AT_RISK"
    BLOCKED = "BLOCKED"


class ModuleCode(str, Enum):
    WATER_HANDLING = "WATER_HANDLING"
    MACHINE_OPERATION = "MACHINE_OPERATION"
    ASEPTIC_TECHNIQUE = "ASEPTIC_TECHNIQUE"
    EMERGENCY_RESPONSE = "EMERGENCY_RESPONSE"
    SUPPLY_STORAGE = "SUPPLY_STORAGE"


class TrainingAttemptStatus(str, Enum):
    RECORDED = "RECORDED"
    SIGNED_OFF = "SIGNED_OFF"


class AssessmentKind(str, Enum):
    INITIAL = "INITIAL"
    REASSESSMENT = "REASSESSMENT"
    POST_MODIFICATION = "POST_MODIFICATION"


class AssessmentResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class AssessmentStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REMEDIATION_REQUIRED = "REMEDIATION_REQUIRED"
    SUPERSEDED = "SUPERSEDED"


class WorkType(str, Enum):
    PLUMBING = "PLUMBING"
    ELECTRICAL = "ELECTRICAL"
    STORAGE_BUILDOUT = "STORAGE_BUILDOUT"


class WorkOrderStatus(str, Enum):
    REQUESTED = "REQUESTED"
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    INSPECTED_PASS = "INSPECTED_PASS"
    INSPECTED_FAIL = "INSPECTED_FAIL"
    CANCELLED = "CANCELLED"


class MachineStatus(str, Enum):
    IN_STOCK = "IN_STOCK"
    ASSIGNED = "ASSIGNED"
    UNDER_MAINTENANCE = "UNDER_MAINTENANCE"
    DECOMMISSIONED = "DECOMMISSIONED"


class EventType(str, Enum):
    PREVENTIVE = "PREVENTIVE"
    REPAIR = "REPAIR"
    DECONTAMINATION = "DECONTAMINATION"


class EventStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class PlanMode(str, Enum):
    IN_CENTER_CHAIR = "IN_CENTER_CHAIR"
    BACKUP_MACHINE = "BACKUP_MACHINE"
    BOTH = "BOTH"


class PlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"
    CLOSED = "CLOSED"


class OrderStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    APPROVED = "APPROVED"
    CLOSED = "CLOSED"
    SUPERSEDED = "SUPERSEDED"
    CANCELLED = "CANCELLED"


class FulfillmentStatus(str, Enum):
    UNFULFILLED = "UNFULFILLED"
    PARTIALLY_DELIVERED = "PARTIALLY_DELIVERED"
    DELIVERED = "DELIVERED"


class AppointmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class LogStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    REVIEWED = "REVIEWED"
    FLAGGED = "FLAGGED"


class DueReason(str, Enum):
    CADENCE = "CADENCE"
    ESCALATION = "ESCALATION"


class ReviewOutcome(str, Enum):
    CONTINUE = "CONTINUE"
    MODIFY_PRESCRIPTION = "MODIFY_PRESCRIPTION"
    REQUIRE_RETRAINING = "REQUIRE_RETRAINING"
    RECOMMEND_TRANSITION = "RECOMMEND_TRANSITION"


class ReviewStatus(str, Enum):
    PENDING = "PENDING"
    SIGNED_OFF = "SIGNED_OFF"
    ESCALATED = "ESCALATED"


class ReservationStatus(str, Enum):
    RESERVED = "RESERVED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class RecordType(str, Enum):
    WASTE = "WASTE"
    RETURN = "RETURN"


class WasteRecordStatus(str, Enum):
    REPORTED = "REPORTED"
    VERIFIED = "VERIFIED"
    CREDITED = "CREDITED"
    REJECTED = "REJECTED"


class Direction(str, Enum):
    HOME_TO_CENTER = "HOME_TO_CENTER"
    CENTER_TO_HOME = "CENTER_TO_HOME"


class ReasonCode(str, Enum):
    PATIENT_CHOICE = "PATIENT_CHOICE"
    MEDICAL_COMPLICATION = "MEDICAL_COMPLICATION"
    SUPPLY_FAILURE = "SUPPLY_FAILURE"
    MACHINE_FAILURE = "MACHINE_FAILURE"
    HOME_UNSUITABLE = "HOME_UNSUITABLE"
    TRAINING_INCOMPLETE = "TRAINING_INCOMPLETE"
    NON_ADHERENCE = "NON_ADHERENCE"


class TransitionStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    REVERSED = "REVERSED"


# -------------------------------------------------------------- entity dicts
# All entities carry common fields per PRD section 2.4.
class DialysisProgram(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    name: str
    review_cadence_treatments: int
    max_missed_log_streak: int
    waste_ratio_alert_threshold: float
    supply_catalog: List[dict]


class Patient(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    program_id: str
    full_name: str
    prescription_treatments_per_week: int
    prescription_units_per_treatment: int
    program_status: str
    ever_home_ready: bool
    retraining_required: bool
    waste_alert_active: bool
    posture: str
    storage_cap_units: int
    on_hand_units: int
    missed_log_streak: int
    no_show_count: int


class TrainingAttempt(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    patient_id: str
    module_code: str
    score_pct: int
    trainer_user_id: str
    is_passing: bool
    signed_off_by_user_id: Optional[str]
    signed_off_at: Optional[str]
    status: str


class HomeAssessment(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    patient_id: str
    assessment_kind: str
    water_chloramine_ppm: float
    electrical_dedicated_circuit: bool
    electrical_voltage_verified: bool
    storage_area_sqft: float
    storage_cap_units: int
    result: str
    assessed_by_user_id: str
    accepted_at: Optional[str]
    status: str


class HomeModificationWorkOrder(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    patient_id: str
    assessment_id: str
    work_type: str
    cost_estimate_cents: int
    scheduled_window_start: Optional[str]
    scheduled_window_end: Optional[str]
    final_cost_cents: Optional[int]
    status: str


class DialysisMachine(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    program_id: str
    serial_number: str
    model: str
    status: str
    assigned_patient_id: Optional[str]
    total_runtime_hours: float
    runtime_hours_at_last_service: float
    maintenance_due: bool


class MaintenanceEvent(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    machine_id: str
    event_type: str
    window_start: str
    window_end: str
    runtime_hours_at_service: Optional[float]
    status: str


class EmergencyBackupPlan(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    patient_id: str
    plan_mode: str
    backup_machine_id: Optional[str]
    last_drill_at: str
    status: str


class SupplyOrder(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    patient_id: str
    order_month: str
    lines: List[dict]
    provisional_total_units: int
    subtotal_cents: int
    handling_fee_cents: int
    discount_cents: int
    grand_total_cents: int
    standard_allowance_units: Optional[int]
    carried_adjustment_units: Optional[int]
    actualized_units: Optional[int]
    adjustment_units: Optional[int]
    delivered_units_total: int
    review_note: Optional[str]
    order_status: str
    fulfillment_status: str


class DeliveryAppointment(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    supply_order_id: str
    window_start: str
    window_end: str
    delivered_units: Optional[int]
    failure_reason: Optional[str]
    status: str


class TreatmentLog(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    patient_id: str
    machine_id: str
    treatment_date: str
    duration_minutes: int
    consumption: List[dict]
    consumption_units: int
    flag_note: Optional[str]
    status: str


class ClinicalReview(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    patient_id: str
    period_start: str
    period_end: str
    due_reason: str
    due_at: str
    outcome: Optional[str]
    adherence_rolling_pct: Optional[float]
    signed_off_at: Optional[str]
    status: str


class InCenterChair(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    program_id: str
    chair_code: str
    in_service: bool


class BackupSlotReservation(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    patient_id: str
    chair_id: str
    slot_start: str
    slot_end: str
    status: str


class WasteReturnRecord(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    patient_id: str
    record_type: str
    activity_month: str
    lines: List[dict]
    total_units: int
    credit_cents: int
    status: str


class TransitionRecord(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    patient_id: str
    reversal_of_id: Optional[str]
    direction: str
    reason_code: str
    effective_from: str
    effective_to: Optional[str]
    status: str
