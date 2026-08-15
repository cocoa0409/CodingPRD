"""Domain types: entity TypedDicts, status enums, role enum for the Hospitalist Census API."""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------

class HospitalistSpecialty(str, Enum):
    INTERNAL_MEDICINE = "INTERNAL_MEDICINE"
    FAMILY_MEDICINE = "FAMILY_MEDICINE"
    ICU = "ICU"


class EmploymentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ON_LEAVE = "ON_LEAVE"
    INACTIVE = "INACTIVE"


class Acuity(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class AdmitSource(str, Enum):
    ED = "ED"
    DIRECT = "DIRECT"
    TRANSFER = "TRANSFER"


class StayType(str, Enum):
    INPATIENT = "INPATIENT"
    OBSERVATION = "OBSERVATION"


class AdmissionStatus(str, Enum):
    ADMITTED = "ADMITTED"
    DISCHARGED = "DISCHARGED"


class ObservationStatus(str, Enum):
    NONE = "NONE"
    OBS_ACTIVE = "OBS_ACTIVE"
    OBS_CONVERTED = "OBS_CONVERTED"
    OBS_CLOSED = "OBS_CLOSED"


class ShiftType(str, Enum):
    DAY = "DAY"
    NIGHT = "NIGHT"


class ShiftState(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class AdmissionQueueStatus(str, Enum):
    QUEUED = "QUEUED"
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"


class AssignmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PENDING_TRANSFER = "PENDING_TRANSFER"
    CLOSED = "CLOSED"


class CloseReason(str, Enum):
    DISCHARGE = "DISCHARGE"
    TRANSFER = "TRANSFER"


class DischargeOrderStatus(str, Enum):
    PLANNED = "PLANNED"
    ORDERED = "ORDERED"
    EXECUTED = "EXECUTED"


class HandoffStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    RETURNED = "RETURNED"
    ACCEPTED = "ACCEPTED"


class ConsultSpecialty(str, Enum):
    CARDIOLOGY = "CARDIOLOGY"
    NEUROLOGY = "NEUROLOGY"
    SURGERY = "SURGERY"
    INFECTIOUS_DISEASE = "INFECTIOUS_DISEASE"
    NEPHROLOGY = "NEPHROLOGY"


class ConsultPriority(str, Enum):
    STAT = "STAT"
    URGENT = "URGENT"
    ROUTINE = "ROUTINE"


class ConsultStatus(str, Enum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    COMPLETED = "COMPLETED"
    ESCALATED = "ESCALATED"
    REOPENED = "REOPENED"
    CLOSED = "CLOSED"


class EncounterType(str, Enum):
    ADMISSION_HCP = "ADMISSION_HCP"
    SUBSEQUENT_VISIT = "SUBSEQUENT_VISIT"
    DISCHARGE_DAY = "DISCHARGE_DAY"
    CONSULT_NOTE = "CONSULT_NOTE"


class EncounterStatus(str, Enum):
    RECORDED = "RECORDED"
    VOIDED = "VOIDED"


class ReportStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINALIZED = "FINALIZED"
    REOPENED = "REOPENED"


class WindowType(str, Enum):
    NIGHT_PRIMARY = "NIGHT_PRIMARY"
    NIGHT_CROSS_COVER = "NIGHT_CROSS_COVER"


class WindowStatus(str, Enum):
    OPEN = "OPEN"
    FULL = "FULL"
    LOCKED = "LOCKED"
    CLOSED = "CLOSED"


class UserRole(str, Enum):
    GROUP_ADMIN = "GroupAdmin"
    HOSPITALIST = "Hospitalist"
    CONSULTING_SPECIALIST = "ConsultingSpecialist"


# ---------------------------------------------------------------------------
# Entity TypedDicts (all entities carry common_fields: id, created_at,
# updated_at, version)
# ---------------------------------------------------------------------------

class Hospitalist(TypedDict, total=False):
    id: str
    full_name: str
    specialty: str
    employment_status: str
    max_census_cap: int
    night_eligible: bool
    current_census: int
    pending_offers: int
    distribution_eligible: bool
    created_at: str
    updated_at: str
    version: int


class Patient(TypedDict, total=False):
    id: str
    mrn: str
    acuity: str
    admit_source: str
    stay_type: str
    admitted_at: str
    admission_status: str
    observation_status: str
    observation_started_at: Optional[str]
    los_midnights: int
    los_blocks: int
    los_alert_flag: bool
    created_at: str
    updated_at: str
    version: int


class Shift(TypedDict, total=False):
    id: str
    hospitalist_id: str
    shift_type: str
    start_at: str
    end_at: str
    state: str
    created_at: str
    updated_at: str
    version: int


class Admission(TypedDict, total=False):
    id: str
    patient_id: str
    status: str
    offered_to_hospitalist_id: Optional[str]
    declined_hospitalist_ids: List[str]
    distribution_score: Optional[float]
    assignment_id: Optional[str]
    offered_at: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Assignment(TypedDict, total=False):
    id: str
    patient_id: str
    hospitalist_id: str
    status: str
    continuity_flag: bool
    assigned_at: str
    closed_at: Optional[str]
    close_reason: Optional[str]
    transfer_target_hospitalist_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DischargeOrder(TypedDict, total=False):
    id: str
    patient_id: str
    ordering_hospitalist_id: str
    status: str
    target_discharge_at: str
    ordered_at: Optional[str]
    executed_at: Optional[str]
    meets_throughput_target: Optional[bool]
    created_at: str
    updated_at: str
    version: int


class Handoff(TypedDict, total=False):
    id: str
    shift_id: str
    receiving_hospitalist_id: str
    patient_ids: List[str]
    status: str
    required_patient_count: int
    covered_patient_count: int
    open_item_count: int
    completeness_score: float
    submitted_at: Optional[str]
    reviewed_at: Optional[str]
    return_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ConsultRequest(TypedDict, total=False):
    id: str
    patient_id: str
    requesting_hospitalist_id: str
    specialty: str
    priority: str
    reason: str
    status: str
    requested_at: str
    sla_deadline: str
    sla_breached: bool
    acknowledged_at: Optional[str]
    completed_at: Optional[str]
    escalation_count: int
    response_minutes: Optional[float]
    created_at: str
    updated_at: str
    version: int


class Encounter(TypedDict, total=False):
    id: str
    hospitalist_id: str
    patient_id: str
    encounter_type: str
    occurred_on: str
    wrvu_value: float
    estimated_wrvu: float
    status: str
    productivity_report_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProductivityReport(TypedDict, total=False):
    id: str
    hospitalist_id: str
    period_start: str
    period_end: str
    status: str
    encounter_count: int
    total_wrvu_provisional: float
    total_wrvu_final: Optional[float]
    wrvu_variance: Optional[float]
    generated_at: str
    finalized_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CoverageWindow(TypedDict, total=False):
    id: str
    window_date: str
    window_type: str
    start_at: str
    end_at: str
    capacity: int
    enrolled_hospitalist_ids: List[str]
    enrolled_count: int
    status: str
    current_load: float
    created_at: str
    updated_at: str
    version: int
