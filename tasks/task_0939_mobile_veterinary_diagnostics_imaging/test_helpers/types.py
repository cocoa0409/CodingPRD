"""Domain types for the Mobile Veterinary Diagnostics & Imaging API.

Status enums, role enum and entity TypedDicts, all named exactly as the PRD
names them.  Three record types are append-only historical facts and carry
only ``id`` and ``created_at`` (no ``updated_at``, no ``version``): the
equipment quality-control record ``QcCheck``, the prepaid-block movement
record ``BlockLedgerEntry`` and the outbound ``Notification``.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    SCHEDULER = "Scheduler"
    BILLING_ADMIN = "BillingAdmin"
    CLINIC_USER = "ClinicUser"
    FIELD_TECH = "FieldTech"
    SPECIALIST = "Specialist"


# --------------------------------------------------------------------------
# Closed enums
# --------------------------------------------------------------------------
class Modality(str, Enum):
    RADIOGRAPHY = "RADIOGRAPHY"
    ULTRASOUND = "ULTRASOUND"
    CT = "CT"
    ECHO = "ECHO"


class Species(str, Enum):
    CANINE = "CANINE"
    FELINE = "FELINE"
    EQUINE = "EQUINE"
    BOVINE = "BOVINE"
    EXOTIC = "EXOTIC"


class StudyKind(str, Enum):
    MOBILE = "MOBILE"
    TELERAD = "TELERAD"


class Priority(str, Enum):
    ROUTINE = "ROUTINE"
    STAT = "STAT"


class PrioritySource(str, Enum):
    NATIVE = "NATIVE"
    UPGRADED = "UPGRADED"


class ClinicStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class BillingHoldStatus(str, Enum):
    CLEAR = "CLEAR"
    HOLD = "HOLD"


class ContractKind(str, Enum):
    PREPAID_BLOCK = "PREPAID_BLOCK"
    PER_STUDY_LIST = "PER_STUDY_LIST"


class ContractStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"


class ServiceStatus(str, Enum):
    IN_SERVICE = "IN_SERVICE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"
    MAINTENANCE = "MAINTENANCE"


class CalibrationStatus(str, Enum):
    UNCALIBRATED = "UNCALIBRATED"
    VALID = "VALID"
    EXPIRED = "EXPIRED"
    QUARANTINED = "QUARANTINED"


class TechnicianStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class SpecialistStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    INACTIVE = "INACTIVE"


class RouteStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    DISPATCHED = "DISPATCHED"
    COMPLETED = "COMPLETED"


class RouteStopStatus(str, Enum):
    PLANNED = "PLANNED"
    EN_ROUTE = "EN_ROUTE"
    ARRIVED = "ARRIVED"
    SERVICED = "SERVICED"
    BUMPED = "BUMPED"
    CANCELLED = "CANCELLED"


class ReferralStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    RETURNED = "RETURNED"
    REJECTED = "REJECTED"
    SCHEDULED = "SCHEDULED"


class AppointmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED_BY_CLINIC = "CANCELLED_BY_CLINIC"
    CANCELLED_BY_PROVIDER = "CANCELLED_BY_PROVIDER"
    NO_SHOW = "NO_SHOW"


class WorkflowStatus(str, Enum):
    ORDERED = "ORDERED"
    ACQUIRED = "ACQUIRED"
    ASSIGNED = "ASSIGNED"
    READ_IN_PROGRESS = "READ_IN_PROGRESS"
    PRELIM_REPORTED = "PRELIM_REPORTED"
    FINALIZED = "FINALIZED"
    REPEAT_PENDING = "REPEAT_PENDING"
    CANCELLED = "CANCELLED"
    NOT_PERFORMED = "NOT_PERFORMED"


class QcStatus(str, Enum):
    PENDING_QC = "PENDING_QC"
    ACCEPTED = "ACCEPTED"
    REPEAT_REQUIRED = "REPEAT_REQUIRED"
    NON_DIAGNOSTIC = "NON_DIAGNOSTIC"


class TatStatus(str, Enum):
    ACCRUING = "ACCRUING"
    PAUSED = "PAUSED"
    MET = "MET"
    BREACHED = "BREACHED"


class BillingStatus(str, Enum):
    UNBILLED = "UNBILLED"
    POSTED = "POSTED"
    REVERSED = "REVERSED"
    NON_BILLABLE = "NON_BILLABLE"


class PriceBasis(str, Enum):
    BLOCK_RATE = "BLOCK_RATE"
    LIST_PRICE = "LIST_PRICE"
    NON_BILLABLE = "NON_BILLABLE"


class HoldReason(str, Enum):
    MISSING_HISTORY = "MISSING_HISTORY"
    ADDENDUM_QUESTION = "ADDENDUM_QUESTION"


class RepeatCause(str, Enum):
    QC_FAILURE = "QC_FAILURE"
    EQUIPMENT_QUARANTINE = "EQUIPMENT_QUARANTINE"
    CLINICIAN_EXTRA_VIEWS = "CLINICIAN_EXTRA_VIEWS"


class AssignmentStatus(str, Enum):
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    HANDED_BACK = "HANDED_BACK"
    COMPLETED = "COMPLETED"
    REVOKED = "REVOKED"


class ReportKind(str, Enum):
    PRELIMINARY = "PRELIMINARY"
    FINAL = "FINAL"
    ADDENDUM = "ADDENDUM"


class ReportStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"
    RETRACTED = "RETRACTED"


class QcResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class PeerReviewStatus(str, Enum):
    SAMPLED = "SAMPLED"
    CONCUR = "CONCUR"
    DISCORDANT = "DISCORDANT"


class InvoiceStatus(str, Enum):
    OPEN = "OPEN"
    FINALIZED = "FINALIZED"


class ChargeLineKind(str, Enum):
    STUDY_READ = "STUDY_READ"
    TRIP_FEE_SHARE = "TRIP_FEE_SHARE"
    STAT_SURCHARGE = "STAT_SURCHARGE"
    ADMIN_FEE = "ADMIN_FEE"
    CANCELLATION_FEE = "CANCELLATION_FEE"


class ChargeLineStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVERSED = "REVERSED"


class BlockLedgerReason(str, Enum):
    DRAW = "DRAW"
    REFUND_QC = "REFUND_QC"


class NotificationKind(str, Enum):
    STOP_BUMPED = "STOP_BUMPED"
    APPOINTMENT_CANCELLED = "APPOINTMENT_CANCELLED"
    STUDY_REPEAT_REQUIRED = "STUDY_REPEAT_REQUIRED"
    REPORT_PUBLISHED = "REPORT_PUBLISHED"
    TAT_BREACHED = "TAT_BREACHED"
    STAT_UPGRADED = "STAT_UPGRADED"


# --------------------------------------------------------------------------
# Entity shapes — full quartet (id / created_at / updated_at / version)
# --------------------------------------------------------------------------
class Clinic(TypedDict):
    id: str
    name: str
    address_zone: str
    status: str
    billing_hold_status: str
    business_open_minute: int
    business_close_minute: int
    business_days: List[int]
    created_at: str
    updated_at: str
    version: int


class ClinicContract(TypedDict):
    id: str
    clinic_id: str
    kind: str
    block_purchased_studies: int
    block_consumed_studies: int
    block_remaining_studies: int
    valid_from: str
    valid_until: str
    suspended: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class MobileUnit(TypedDict):
    id: str
    name: str
    service_status: str
    max_stops: int
    max_shift_minutes: int
    created_at: str
    updated_at: str
    version: int


class Equipment(TypedDict):
    id: str
    assigned_unit_id: Optional[str]
    modality: str
    serial_label: str
    calibration_valid_from: Optional[str]
    calibration_valid_until: Optional[str]
    calibration_status: str
    usage_count_since_qc: int
    last_passing_qc_at: Optional[str]
    quarantined_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Technician(TypedDict):
    id: str
    full_name: str
    certified_modalities: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Specialist(TypedDict):
    id: str
    full_name: str
    modality_privileges: List[str]
    species_privileges: List[str]
    stat_eligible: bool
    status: str
    open_read_count: int
    workload_score: int
    created_at: str
    updated_at: str
    version: int


class Route(TypedDict):
    id: str
    mobile_unit_id: str
    technician_id: str
    service_date: str
    shift_start_minute: int
    shift_end_minute: int
    status: str
    stop_count: int
    planned_occupied_minutes: int
    actual_occupied_minutes: int
    slack_minutes: int
    published_at: Optional[str]
    dispatched_at: Optional[str]
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RouteStop(TypedDict):
    id: str
    route_id: str
    clinic_id: str
    bumped_by_stop_id: Optional[str]
    sequence: int
    planned_arrival_minute: int
    service_minutes: int
    drive_minutes_from_prev: int
    stop_priority: str
    status: str
    trip_fee_cents: int
    arrived_at: Optional[str]
    departed_at: Optional[str]
    actual_service_minutes: int
    cancel_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Referral(TypedDict):
    id: str
    clinic_id: str
    patient_name: str
    species: str
    study_kind: str
    requested_modality: str
    priority: str
    clinical_history: Optional[str]
    status: str
    return_reason: Optional[str]
    reject_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Appointment(TypedDict):
    id: str
    referral_id: str
    route_stop_id: Optional[str]
    status: str
    ordered_studies_count: int
    pending_studies_count: int
    acquired_studies_count: int
    cancelled_studies_count: int
    not_performed_studies_count: int
    cancel_reason: Optional[str]
    cancelled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Study(TypedDict):
    id: str
    appointment_id: str
    equipment_id: Optional[str]
    technician_id: Optional[str]
    repeat_of_study_id: Optional[str]
    study_kind: str
    species: str
    modality: str
    body_region: str
    priority: str
    priority_source: str
    workflow_status: str
    qc_status: str
    tat_status: str
    billing_status: str
    image_count: int
    acquired_at: Optional[str]
    escalated_at: Optional[str]
    tat_anchor_at: Optional[str]
    tat_target_minutes: int
    tat_deadline_at: Optional[str]
    tat_elapsed_minutes: int
    tat_paused_minutes: int
    tat_accrued_minutes: int
    pause_started_at: Optional[str]
    hold_reason: Optional[str]
    repeat_cause: Optional[str]
    repeat_count: int
    read_attempt_count: int
    cancellation_fee_cents: int
    cancel_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReadAssignment(TypedDict):
    id: str
    study_id: str
    specialist_id: str
    attempt_number: int
    status: str
    offered_at: str
    responded_at: Optional[str]
    decline_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Report(TypedDict):
    id: str
    study_id: str
    author_specialist_id: str
    supersedes_report_id: Optional[str]
    kind: str
    report_version: int
    status: str
    findings: str
    published_at: Optional[str]
    retracted_at: Optional[str]
    retract_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PeerReview(TypedDict):
    id: str
    report_id: str
    reviewer_specialist_id: str
    status: str
    score: Optional[int]
    outcome_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    clinic_id: str
    period_start: str
    period_end: str
    status: str
    total_cents: int
    finalized_total_cents: Optional[int]
    finalized_at: Optional[str]
    posted_study_count: int
    created_at: str
    updated_at: str
    version: int


class ChargeLine(TypedDict):
    id: str
    invoice_id: str
    study_id: str
    kind: str
    amount_cents: int
    status: str
    reversal_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------
# Append-only historical facts — ONLY id and created_at
# --------------------------------------------------------------------------
class QcCheck(TypedDict):
    id: str
    equipment_id: str
    performed_by_technician_id: str
    result: str
    note: Optional[str]
    performed_at: str
    affected_study_count: int
    created_at: str


class BlockLedgerEntry(TypedDict):
    id: str
    contract_id: str
    study_id: Optional[str]
    delta_studies: int
    balance_after_studies: int
    reason: str
    created_at: str


class Notification(TypedDict):
    id: str
    clinic_id: str
    study_id: Optional[str]
    kind: str
    message: str
    created_at: str
