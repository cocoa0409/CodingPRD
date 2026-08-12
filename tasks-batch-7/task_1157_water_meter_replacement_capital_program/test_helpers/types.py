"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import Any, Optional, TypedDict


class UserRole(str, Enum):
    PROGRAM_MANAGER = "ProgramManager"
    SCHEDULER = "Scheduler"
    FIELD_CONTRACTOR = "FieldContractor"
    QUALITY_AUDITOR = "QualityAuditor"
    AMI_OPERATOR = "AmiOperator"
    CUSTOMER_SERVICE = "CustomerService"


class ProgramStatus(str, Enum):
    PLANNING = "PLANNING"
    ACTIVE = "ACTIVE"
    CLOSING = "CLOSING"
    CLOSED = "CLOSED"


class BudgetPosture(str, Enum):
    FUNDED = "FUNDED"
    TIGHT = "TIGHT"
    OVERRUN = "OVERRUN"


class ContractorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ServiceAccountStatus(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    IN_PROGRAM = "IN_PROGRAM"
    REPLACED = "REPLACED"
    EXEMPTED = "EXEMPTED"


class MeterLocation(str, Enum):
    INSIDE = "INSIDE"
    OUTSIDE = "OUTSIDE"


class PriorityTier(str, Enum):
    STANDARD = "STANDARD"
    SENSITIVE = "SENSITIVE"
    CRITICAL = "CRITICAL"


class MeterStatus(str, Enum):
    IN_STOCK = "IN_STOCK"
    INSTALLED = "INSTALLED"
    REMOVED = "REMOVED"
    BENCH_PASSED = "BENCH_PASSED"
    BENCH_FAILED = "BENCH_FAILED"
    DISPOSED = "DISPOSED"
    RETURNED_TO_VENDOR = "RETURNED_TO_VENDOR"


class SizeCode(str, Enum):
    S_5_8 = "S_5_8"
    S_3_4 = "S_3_4"
    S_1 = "S_1"
    S_1_5 = "S_1_5"
    S_2 = "S_2"


class MeterTechnology(str, Enum):
    LEGACY = "LEGACY"
    AMI = "AMI"


class WaveStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    LOCKED = "LOCKED"
    COMPLETE = "COMPLETE"
    CANCELLED = "CANCELLED"


class WorkOrderLifecycle(str, Enum):
    CREATED = "CREATED"
    NOTIFIED = "NOTIFIED"
    SCHEDULED = "SCHEDULED"
    ACCESS_FAILED = "ACCESS_FAILED"
    SWAPPED = "SWAPPED"
    RECONCILED = "RECONCILED"
    AMI_VERIFIED = "AMI_VERIFIED"
    QA_REVIEW = "QA_REVIEW"
    QA_FAILED = "QA_FAILED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class HoldStatus(str, Enum):
    CLEAR = "CLEAR"
    ON_HOLD = "ON_HOLD"


class NotificationChannel(str, Enum):
    USPS_MAIL = "USPS_MAIL"
    CERTIFIED_MAIL = "CERTIFIED_MAIL"
    DOOR_HANGER = "DOOR_HANGER"
    PHONE = "PHONE"
    EMAIL = "EMAIL"


class NotificationStatus(str, Enum):
    SENT = "SENT"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"
    RETURNED = "RETURNED"


class DeliveryOutcome(str, Enum):
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"
    RETURNED = "RETURNED"


class AppointmentWindow(str, Enum):
    AM = "AM"
    PM = "PM"
    EVE = "EVE"


class AppointmentStatus(str, Enum):
    BOOKED = "BOOKED"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    NO_ACCESS = "NO_ACCESS"
    CANCELLED_BY_CUSTOMER = "CANCELLED_BY_CUSTOMER"
    SUPERSEDED = "SUPERSEDED"


class NoAccessStage(str, Enum):
    STAGE_1_DOOR_HANGER = "STAGE_1_DOOR_HANGER"
    STAGE_2_CERTIFIED_MAIL = "STAGE_2_CERTIFIED_MAIL"
    STAGE_3_PHONE_CAMPAIGN = "STAGE_3_PHONE_CAMPAIGN"
    STAGE_4_FIELD_VISIT = "STAGE_4_FIELD_VISIT"


class NoAccessCaseStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"


class NoAccessResolution(str, Enum):
    ACCESS_GAINED = "ACCESS_GAINED"
    ACCOUNT_EXEMPTED = "ACCOUNT_EXEMPTED"
    FORCED_ENTRY = "FORCED_ENTRY"


class ReadType(str, Enum):
    FINAL = "FINAL"
    INITIAL = "INITIAL"
    VERIFICATION = "VERIFICATION"
    ESTIMATED = "ESTIMATED"


class ReadSource(str, Enum):
    FIELD_CREW = "FIELD_CREW"
    AMI_NETWORK = "AMI_NETWORK"
    CUSTOMER = "CUSTOMER"
    SYSTEM_ESTIMATE = "SYSTEM_ESTIMATE"


class RegistrationStatus(str, Enum):
    REGISTERED = "REGISTERED"
    COMM_VERIFIED = "COMM_VERIFIED"
    COMM_FAILED = "COMM_FAILED"
    REPLACED = "REPLACED"


class BenchTestResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class ComplaintStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    BENCH_TEST_ORDERED = "BENCH_TEST_ORDERED"
    ADJUSTED = "ADJUSTED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


class AdjudicationVariant(str, Enum):
    REGISTRATION_ERROR = "REGISTRATION_ERROR"
    GOODWILL_TIERED = "GOODWILL_TIERED"


class AdjudicationDecision(str, Enum):
    ADJUSTED = "ADJUSTED"
    DENIED = "DENIED"


class AuditType(str, Enum):
    SAMPLED = "SAMPLED"
    FOR_CAUSE = "FOR_CAUSE"


class AuditResultStatus(str, Enum):
    PENDING = "PENDING"
    PASS = "PASS"
    FAIL = "FAIL"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DISPUTED = "DISPUTED"


# --- Entity TypedDicts -------------------------------------------------------
# All entities below carry common fields (id, created_at, updated_at, version)
# except MeterReading, which is append-only: id + created_at only.


class Program(TypedDict, total=False):
    id: str
    name: str
    fiscal_year: str
    budget_total_cents: int
    target_meter_count: int
    rate_per_ccf_cents: int
    default_unit_allowance_cents: int
    notice_days: int
    budget_committed_cents: int
    budget_spent_cents: int
    budget_available_cents: int
    budget_posture: str
    completed_meter_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Contractor(TypedDict, total=False):
    id: str
    program_id: str
    name: str
    crew_capacity_per_window: int
    unit_price_cents: int
    quality_score_bp: int
    audits_failed_count: int
    installs_completed_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceAccount(TypedDict, total=False):
    id: str
    account_number: str
    service_address: str
    meter_location: str
    customer_name: str
    customer_phone: str
    priority_tier: str
    avg_daily_usage_ccf: float
    last_billed_read_value: int
    last_billed_read_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Meter(TypedDict, total=False):
    id: str
    serial_number: str
    size_code: str
    technology: str
    service_account_id: Optional[str]
    installed_read_value: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Wave(TypedDict, total=False):
    id: str
    program_id: str
    wave_number: int
    window_start: str
    window_end: str
    capacity: int
    committed_count: int
    completed_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class WorkOrder(TypedDict, total=False):
    id: str
    wave_id: str
    service_account_id: str
    contractor_id: Optional[str]
    old_meter_id: str
    new_meter_id: Optional[str]
    committed_amount_cents: int
    provisional_trueup_cents: Optional[int]
    trueup_amount_cents: Optional[int]
    trueup_delta_cents: Optional[int]
    no_access_strikes: int
    closed_at: Optional[str]
    lifecycle_status: str
    hold_status: str
    created_at: str
    updated_at: str
    version: int


class CustomerNotification(TypedDict, total=False):
    id: str
    work_order_id: str
    no_access_case_id: Optional[str]
    channel: str
    sent_at: str
    delivered_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Appointment(TypedDict, total=False):
    id: str
    work_order_id: str
    contractor_id: str
    slot_date: str
    window: str
    attempt_number: int
    status: str
    created_at: str
    updated_at: str
    version: int


class NoAccessCase(TypedDict, total=False):
    id: str
    work_order_id: str
    stage: str
    strikes_at_open: int
    status: str
    resolution: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MeterReading(TypedDict, total=False):
    # Append-only event: id + created_at only; NO updated_at, NO version.
    id: str
    work_order_id: str
    meter_id: str
    read_type: str
    value: int
    source: str
    read_at: str
    created_at: str


class EndpointRegistration(TypedDict, total=False):
    id: str
    work_order_id: str
    meter_id: str
    endpoint_serial: str
    registered_at: str
    reads_received_count: int
    rssi_sum_dbm: int
    status: str
    created_at: str
    updated_at: str
    version: int


class BenchTest(TypedDict, total=False):
    id: str
    meter_id: str
    work_order_id: Optional[str]
    complaint_id: Optional[str]
    measured_low_ccf: float
    measured_mid_ccf: float
    measured_high_ccf: float
    accuracy_low_pct: float
    accuracy_mid_pct: float
    accuracy_high_pct: float
    weighted_accuracy_pct: float
    result: str
    tested_at: str
    created_at: str
    updated_at: str
    version: int


class HighBillComplaint(TypedDict, total=False):
    id: str
    service_account_id: str
    work_order_id: str
    claimed_bill_cents: int
    baseline_bill_cents: int
    billing_period_start: str
    billing_period_end: str
    variance_pct: float
    bench_test_id: Optional[str]
    adjustment_cents: Optional[int]
    adjudication_variant: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class QualityAudit(TypedDict, total=False):
    id: str
    work_order_id: str
    contractor_id: str
    audit_type: str
    checks_total: Optional[int]
    checks_passed: Optional[int]
    defects_found: Optional[int]
    recorded_at: Optional[str]
    result_status: str
    created_at: str
    updated_at: str
    version: int


class ContractorInvoice(TypedDict, total=False):
    id: str
    contractor_id: str
    program_id: str
    period_start: str
    period_end: str
    units_completed: int
    gross_amount_cents: int
    bonus_cents: int
    penalty_cents: int
    retainage_cents: int
    net_amount_cents: int
    dispute_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
