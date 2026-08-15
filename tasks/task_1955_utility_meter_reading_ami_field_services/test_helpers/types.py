"""Domain types: entity TypedDicts, status enums, role enum.

Mirrors the resource model described in PRD sections 2.5 and 3.x. Every
resource carries the common quartet (id, created_at, updated_at, version).
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Enums (string values exactly as the PRD spells them)
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    METER_OPS_ADMIN = "MeterOpsAdmin"
    DISPATCHER = "Dispatcher"
    FIELD_TECHNICIAN = "FieldTechnician"
    BILLING_LIAISON = "BillingLiaison"
    INVESTIGATOR = "Investigator"


class TechnicianStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class EstimationMethod(str, Enum):
    TRAILING_AVERAGE = "TRAILING_AVERAGE"
    SAME_PERIOD_LAST_YEAR = "SAME_PERIOD_LAST_YEAR"


class MeterType(str, Enum):
    HANDHELD = "HANDHELD"
    AMI = "AMI"


class MeterStatus(str, Enum):
    IN_STOCK = "IN_STOCK"
    IN_SERVICE = "IN_SERVICE"
    REMOVED = "REMOVED"
    RETIRED = "RETIRED"


class EndpointCommsStatus(str, Enum):
    COMMUNICATING = "COMMUNICATING"
    DEGRADED = "DEGRADED"
    NON_COMMUNICATING = "NON_COMMUNICATING"
    FAILED = "FAILED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class TamperStatus(str, Enum):
    NONE = "NONE"
    SUSPECTED = "SUSPECTED"
    CONFIRMED = "CONFIRMED"


class PeriodStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    WINDOW_OPEN = "WINDOW_OPEN"
    WINDOW_CLOSED = "WINDOW_CLOSED"
    BILLED = "BILLED"
    CLOSED = "CLOSED"


class RouteShift(str, Enum):
    AM = "AM"
    PM = "PM"
    FULL = "FULL"


class RouteStatus(str, Enum):
    DRAFT = "DRAFT"
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    RECONCILED = "RECONCILED"
    CANCELLED = "CANCELLED"


class StopStatus(str, Enum):
    PENDING = "PENDING"
    READ_CAPTURED = "READ_CAPTURED"
    NO_READ_PENDING = "NO_READ_PENDING"
    SKIPPED_HAZARD = "SKIPPED_HAZARD"
    ESTIMATED = "ESTIMATED"
    VALIDATED = "VALIDATED"
    SUPERSEDED = "SUPERSEDED"
    CANCELLED = "CANCELLED"


class ReadSource(str, Enum):
    HANDHELD = "HANDHELD"
    REREAD = "REREAD"
    AMI_REMOTE = "AMI_REMOTE"
    ESTIMATE = "ESTIMATE"
    EXCHANGE_FINAL = "EXCHANGE_FINAL"
    EXCHANGE_INITIAL = "EXCHANGE_INITIAL"


class ReadStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    VALIDATED = "VALIDATED"
    REJECTED = "REJECTED"
    ESTIMATED = "ESTIMATED"
    SUPERSEDED = "SUPERSEDED"


class HazardType(str, Enum):
    DOG = "DOG"
    ACCESS = "ACCESS"
    LOCKED_GATE = "LOCKED_GATE"
    CHEMICAL = "CHEMICAL"
    OTHER = "OTHER"


class Severity(str, Enum):
    LOW = "LOW"
    HIGH = "HIGH"


class FlagStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    CLEARED = "CLEARED"


class WorkOrderType(str, Enum):
    RE_READ = "RE_READ"
    EXCHANGE = "EXCHANGE"
    TAMPER_CHECK = "TAMPER_CHECK"
    ENDPOINT_SWAP = "ENDPOINT_SWAP"


class WorkOrderStatus(str, Enum):
    OPEN = "OPEN"
    DISPATCHED = "DISPATCHED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    REWORK = "REWORK"
    VERIFIED = "VERIFIED"
    CANCELLED = "CANCELLED"


class IndicationType(str, Enum):
    TAMPER_FLAG = "TAMPER_FLAG"
    THEFT_REPORT = "THEFT_REPORT"
    USAGE_ANOMALY = "USAGE_ANOMALY"


class InvestigationStatus(str, Enum):
    OPEN = "OPEN"
    EVIDENCE_GATHERING = "EVIDENCE_GATHERING"
    PENDING_DISPOSITION = "PENDING_DISPOSITION"
    CONFIRMED_THEFT = "CONFIRMED_THEFT"
    CLEARED = "CLEARED"
    CLOSED = "CLOSED"


class CampaignStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    COMPLETED = "COMPLETED"
    CLOSED = "CLOSED"


class EnrollmentStatus(str, Enum):
    ENROLLED = "ENROLLED"
    WORK_ORDER_CREATED = "WORK_ORDER_CREATED"
    REPLACED = "REPLACED"
    WITHDRAWN = "WITHDRAWN"


class SnapshotStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"


# ---------------------------------------------------------------------------
# Entity TypedDicts (all carry the common quartet per PRD section 2.5)
# ---------------------------------------------------------------------------

class FieldTechnician(TypedDict):
    id: str
    display_name: str
    technician_status: str
    created_at: str
    updated_at: str
    version: int


class ServiceAccount(TypedDict):
    id: str
    account_number: str
    service_address: str
    billing_cycle_code: str
    estimation_method: str
    account_status: str
    current_meter_id: Optional[str]
    last_validated_read_value: Optional[int]
    last_validated_read_at: Optional[str]
    estimated_read_streak: int
    created_at: str
    updated_at: str
    version: int


class Meter(TypedDict):
    id: str
    serial_number: str
    meter_type: str
    meter_status: str
    endpoint_comms_status: str
    tamper_status: str
    installed_service_account_id: Optional[str]
    consecutive_missed_days: int
    non_communicating_since: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BillingCyclePeriod(TypedDict):
    id: str
    cycle_code: str
    period_start_date: str
    period_end_date: str
    read_window_open_date: str
    read_window_close_date: str
    bill_run_date: str
    period_status: str
    unresolved_stop_count: int
    created_at: str
    updated_at: str
    version: int


class Route(TypedDict):
    id: str
    billing_cycle_period_id: str
    scheduled_date: str
    route_shift: str
    two_person_crew: bool
    technician_id: Optional[str]
    route_status: str
    stops_total: int
    captured_stop_count: int
    read_rate_percent: Optional[float]
    net_read_rate_percent: Optional[float]
    created_at: str
    updated_at: str
    version: int


class RouteStop(TypedDict):
    id: str
    route_id: str
    service_account_id: str
    billing_cycle_period_id: str
    sequence_number: int
    stop_status: str
    no_read_reason: Optional[str]
    hazard_flag_id: Optional[str]
    current_read_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MeterRead(TypedDict):
    id: str
    route_stop_id: Optional[str]
    service_account_id: str
    meter_id: str
    read_value: int
    read_at: str
    read_source: str
    read_status: str
    estimation_method: Optional[str]
    tamper_indication: bool
    supersedes_read_id: Optional[str]
    rejection_reason: Optional[str]
    is_billable: bool
    created_at: str
    updated_at: str
    version: int


class HazardFlag(TypedDict):
    id: str
    service_account_id: str
    hazard_type: str
    severity: str
    flag_status: str
    reported_by_technician_id: str
    reported_at: str
    expires_at: str
    renewed_count: int
    created_at: str
    updated_at: str
    version: int


class WorkOrder(TypedDict):
    id: str
    work_order_type: str
    service_account_id: str
    meter_id: Optional[str]
    route_stop_id: Optional[str]
    investigation_id: Optional[str]
    campaign_enrollment_id: Optional[str]
    scheduled_date: str
    work_shift: str
    notes: Optional[str]
    technician_id: Optional[str]
    work_order_status: str
    new_meter_id: Optional[str]
    old_final_read_value: Optional[int]
    new_initial_read_value: Optional[int]
    reread_value: Optional[int]
    reread_at: Optional[str]
    evidence_note: Optional[str]
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Investigation(TypedDict):
    id: str
    service_account_id: str
    meter_id: str
    indication_type: str
    investigation_status: str
    opened_by_user_id: str
    closed_by_user_id: Optional[str]
    triggering_read_id: Optional[str]
    exchange_work_order_id: Optional[str]
    theft_window_months: Optional[int]
    monthly_estimated_kwh: Optional[List[int]]
    backbill_cents: Optional[int]
    evidence_notes: List[str]
    created_at: str
    updated_at: str
    version: int


class ReplacementCampaign(TypedDict):
    id: str
    campaign_name: str
    quota: int
    campaign_status: str
    enrolled_count: int
    replaced_count: int
    withdrawn_count: int
    created_at: str
    updated_at: str
    version: int


class CampaignEnrollment(TypedDict):
    id: str
    campaign_id: str
    meter_id: str
    enrollment_status: str
    work_order_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OpsSnapshot(TypedDict):
    id: str
    snapshot_at: str
    snapshot_status: str
    eligible_stop_count: int
    covered_stop_count: int
    backlog_count: int
    backlog_aged_7plus_count: int
    estimated_read_count: int
    validated_read_count: int
    read_rate_percent: Optional[float]
    net_read_rate_percent: Optional[float]
    sla_breach: Optional[bool]
    created_at: str
    updated_at: str
    version: int
