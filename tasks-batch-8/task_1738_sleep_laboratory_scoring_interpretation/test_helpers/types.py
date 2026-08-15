"""Domain types: entity TypedDicts, status enums, role enum.

All resources carry the common system-managed fields (id, created_at,
updated_at, version) described in PRD "Common Resource Properties".
"""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    SCHEDULER = "Scheduler"
    SLEEP_TECHNOLOGIST = "SleepTechnologist"
    SCORER = "Scorer"
    INTERPRETING_PHYSICIAN = "InterpretingPhysician"
    DME_COORDINATOR = "DmeCoordinator"
    LAB_DIRECTOR = "LabDirector"


class StudyType(str, Enum):
    PSG_DIAGNOSTIC = "PSG_DIAGNOSTIC"
    HST = "HST"
    SPLIT_NIGHT = "SPLIT_NIGHT"
    TITRATION_PAP = "TITRATION_PAP"


class OrderPriority(str, Enum):
    ROUTINE = "ROUTINE"
    STAT = "STAT"


class ReferralOrderStatus(str, Enum):
    RECEIVED = "RECEIVED"
    AUTH_IN_PROGRESS = "AUTH_IN_PROGRESS"
    AUTHORIZED = "AUTHORIZED"
    AUTH_DENIED = "AUTH_DENIED"
    SCHEDULED = "SCHEDULED"
    NEEDS_PROVIDER_REVIEW = "NEEDS_PROVIDER_REVIEW"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class AuthorizationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"
    WITHDRAWN = "WITHDRAWN"


class StaffingStatus(str, Enum):
    PLANNED = "PLANNED"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"


class SleepStudyStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    SCORING_QUEUED = "SCORING_QUEUED"
    SCORING_IN_PROGRESS = "SCORING_IN_PROGRESS"
    SCORED = "SCORED"
    INTERPRETATION_IN_PROGRESS = "INTERPRETATION_IN_PROGRESS"
    INTERPRETED = "INTERPRETED"
    REPORT_FINALIZED = "REPORT_FINALIZED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"
    TECHNICAL_FAILURE = "TECHNICAL_FAILURE"


class SplitOutcome(str, Enum):
    CONVERT_TO_TITRATION = "CONVERT_TO_TITRATION"
    CONTINUE_DIAGNOSTIC = "CONTINUE_DIAGNOSTIC"


class ScoringTaskStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    RETURNED_FOR_REVISION = "RETURNED_FOR_REVISION"
    RECALLED = "RECALLED"


class AssignmentKind(str, Enum):
    PRIMARY = "PRIMARY"
    RELIABILITY_RESCORE = "RELIABILITY_RESCORE"


class ReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SIGNED = "SIGNED"
    FINALIZED = "FINALIZED"
    ADDENDUM_OPEN = "ADDENDUM_OPEN"
    SUPERSEDED = "SUPERSEDED"


class Severity(str, Enum):
    NORMAL = "NORMAL"
    MILD = "MILD"
    MODERATE = "MODERATE"
    SEVERE = "SEVERE"


class PrescriptionStatus(str, Enum):
    DRAFT = "DRAFT"
    ORDERED = "ORDERED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"
    SUPERSEDED = "SUPERSEDED"


class DeviceType(str, Enum):
    CPAP = "CPAP"
    APAP = "APAP"
    BIPAP = "BIPAP"


class MaskType(str, Enum):
    NASAL = "NASAL"
    FULL_FACE = "FULL_FACE"
    NASAL_PILLOWS = "NASAL_PILLOWS"


class DmeOrderStatus(str, Enum):
    DISPATCHED = "DISPATCHED"
    DELIVERED = "DELIVERED"
    DECLINED = "DECLINED"
    CANCELLED = "CANCELLED"
    FOLLOW_UP_PASSED = "FOLLOW_UP_PASSED"
    ADHERENCE_REVIEW = "ADHERENCE_REVIEW"
    FOLLOW_UP_RESOLVED = "FOLLOW_UP_RESOLVED"


class ResolutionAction(str, Enum):
    CONTINUE_THERAPY = "CONTINUE_THERAPY"
    ESCALATE_TO_PHYSICIAN = "ESCALATE_TO_PHYSICIAN"


class ReliabilityStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    CONSISTENT = "CONSISTENT"
    WATCH = "WATCH"
    REMEDIATION = "REMEDIATION"


class CaseStatus(str, Enum):
    OPEN = "OPEN"
    ADJUDICATED = "ADJUDICATED"


class Patient(TypedDict, total=False):
    id: str
    mrn: str
    full_name: str
    date_of_birth: str
    created_at: str
    updated_at: str
    version: int


class ReferralOrder(TypedDict, total=False):
    id: str
    patient_id: str
    ordering_provider_name: str
    requested_study_type: str
    icd10_primary: str
    priority: str
    no_show_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class InsuranceAuthorization(TypedDict, total=False):
    id: str
    order_id: str
    payer_name: str
    authorization_number: str
    approved_nights: int
    window_start: str
    window_end: str
    decided_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Bed(TypedDict, total=False):
    id: str
    room_label: str
    titration_capable: bool
    is_active: bool
    created_at: str
    updated_at: str
    version: int


class Technologist(TypedDict, total=False):
    id: str
    full_name: str
    credential: str
    is_active: bool
    created_at: str
    updated_at: str
    version: int


class Scorer(TypedDict, total=False):
    id: str
    full_name: str
    credential: str
    npi: str
    reliability_pool: bool
    is_active: bool
    consecutive_nonconcordant: int
    rolling_agreement_index: Optional[float]
    reliability_status: str
    created_at: str
    updated_at: str
    version: int


class Physician(TypedDict, total=False):
    id: str
    full_name: str
    npi: str
    board_certified: bool
    is_active: bool
    created_at: str
    updated_at: str
    version: int


class StaffingAssignment(TypedDict, total=False):
    id: str
    technologist_id: str
    shift_date: str
    patient_capacity: int
    confirmed_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class SleepStudy(TypedDict, total=False):
    id: str
    patient_id: str
    order_id: str
    bed_id: Optional[str]
    study_type: str
    scheduled_date: str
    split_outcome: Optional[str]
    split_diagnostic_minutes: Optional[int]
    split_partial_ahi: Optional[float]
    acquisition_completed_at: Optional[str]
    total_recording_time_minutes: Optional[int]
    titration_final_pressure_cm: Optional[float]
    leak_95th_l_min: Optional[float]
    accepted_ahi: Optional[float]
    accepted_rdi: Optional[float]
    accepted_rei: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class ScoringTask(TypedDict, total=False):
    id: str
    study_id: str
    scorer_id: str
    assignment_kind: str
    obstructive_apneas: Optional[int]
    central_apneas: Optional[int]
    mixed_apneas: Optional[int]
    hypopneas: Optional[int]
    reras: Optional[int]
    epochs_total: Optional[int]
    total_sleep_time_minutes: Optional[int]
    total_recording_time_minutes: Optional[int]
    ahi: Optional[float]
    rdi: Optional[float]
    rei: Optional[float]
    submitted_at: Optional[str]
    returned_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class InterpretationReport(TypedDict, total=False):
    id: str
    study_id: str
    physician_id: str
    primary_scoring_task_id: str
    diagnosis_code: str
    index_at_interpretation: Optional[float]
    severity: Optional[str]
    turnaround_business_hours: Optional[float]
    turnaround_calendar_hours: Optional[float]
    sla_breached: Optional[bool]
    signed_at: Optional[str]
    finalized_at: Optional[str]
    addendum_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TherapyPrescription(TypedDict, total=False):
    id: str
    report_id: str
    study_id: str
    device_type: str
    cpap_pressure_cm: Optional[float]
    apap_min_cm: Optional[float]
    apap_max_cm: Optional[float]
    bipap_ipap_cm: Optional[float]
    bipap_epap_cm: Optional[float]
    mask_type: str
    humidification: bool
    ordered_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DmeOrder(TypedDict, total=False):
    id: str
    prescription_id: str
    vendor_name: str
    dispatched_at: Optional[str]
    delivered_at: Optional[str]
    follow_up_usage_hours_avg: Optional[float]
    follow_up_compliant_nights_percent: Optional[float]
    adherence_compliant: Optional[bool]
    resolution_action: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class InterRaterCase(TypedDict, total=False):
    id: str
    study_id: str
    primary_task_id: str
    rescore_task_id: str
    epochs_concordant: Optional[int]
    ahi_primary: Optional[float]
    ahi_rescore: Optional[float]
    ahi_delta: Optional[float]
    percent_agreement: Optional[float]
    concordant: Optional[bool]
    adjudicated_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
