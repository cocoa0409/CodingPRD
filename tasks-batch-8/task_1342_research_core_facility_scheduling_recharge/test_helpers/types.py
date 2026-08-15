"""Domain types: entity TypedDicts, status enums, role enum (PRD §2, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    FACILITY_ADMIN = "FacilityAdmin"
    CORE_STAFF = "CoreStaff"
    FINANCE_OFFICER = "FinanceOfficer"
    RESEARCHER = "Researcher"
    EXTERNAL_CLIENT = "ExternalClient"


class UserStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class Affiliation(str, Enum):
    INTERNAL = "INTERNAL"
    EXTERNAL = "EXTERNAL"


class InstrumentStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    DOWN = "DOWN"
    MAINTENANCE = "MAINTENANCE"
    RETIRED = "RETIRED"


class TrainingRecordStatus(str, Enum):
    ENROLLED = "ENROLLED"
    CERTIFIED = "CERTIFIED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class GrantStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXHAUSTED = "EXHAUSTED"
    EXPIRED = "EXPIRED"
    CLOSED = "CLOSED"


class RateSetStatus(str, Enum):
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    EFFECTIVE = "EFFECTIVE"
    SUPERSEDED = "SUPERSEDED"


class BookingStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"
    PREEMPTED = "PREEMPTED"
    REJECTED = "REJECTED"


class BookingPriority(str, Enum):
    STANDARD = "STANDARD"
    PRIORITY = "PRIORITY"


class CancellationReason(str, Enum):
    USER = "USER"
    STAFF = "STAFF"
    PREEMPTION = "PREEMPTION"
    DOWNTIME = "DOWNTIME"
    USER_SUSPENDED = "USER_SUSPENDED"
    INSTRUMENT_RETIRED = "INSTRUMENT_RETIRED"


class UsageLogStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    VALIDATED = "VALIDATED"
    REJECTED = "REJECTED"


class RechargeBatchStatus(str, Enum):
    OPEN = "OPEN"
    FINALIZED = "FINALIZED"


class RechargeEntryKind(str, Enum):
    USAGE = "USAGE"
    PENALTY = "PENALTY"
    ADJUSTMENT = "ADJUSTMENT"


class RechargeEntryStatus(str, Enum):
    PENDING = "PENDING"
    BILLED = "BILLED"
    PAID = "PAID"
    DISPUTED = "DISPUTED"
    WRITTEN_OFF = "WRITTEN_OFF"


class SubsidyApplicationKind(str, Enum):
    STARTUP = "STARTUP"
    SUBSIDY = "SUBSIDY"


class SubsidyApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class SubsidyAwardStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXHAUSTED = "EXHAUSTED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class MaintenanceContractStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    TERMINATED = "TERMINATED"


class DowntimeEventKind(str, Enum):
    UNSCHEDULED_FAILURE = "UNSCHEDULED_FAILURE"
    PREVENTIVE_MAINTENANCE = "PREVENTIVE_MAINTENANCE"
    CALIBRATION = "CALIBRATION"


class DowntimeEventStatus(str, Enum):
    REPORTED = "REPORTED"
    CONFIRMED = "CONFIRMED"
    RESOLVED = "RESOLVED"
    CANCELLED = "CANCELLED"


class PublicationStatus(str, Enum):
    REPORTED = "REPORTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class FiscalYearStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class User(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    affiliation: str
    department: Optional[str]
    is_pi: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Instrument(TypedDict, total=False):
    id: str
    name: str
    model: str
    location: str
    requires_training: bool
    booking_buffer_minutes: int
    min_booking_minutes: int
    max_booking_minutes: int
    cancellation_free_notice_hours: int
    late_cancel_penalty_pct: float
    no_show_penalty_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class TrainingRecord(TypedDict, total=False):
    id: str
    user_id: str
    instrument_id: str
    status: str
    certified_at: Optional[str]
    expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Grant(TypedDict, total=False):
    id: str
    grant_code: str
    pi_user_id: str
    title: str
    budget_total_cents: int
    authorized_user_ids: List[str]
    start_date: str
    end_date: str
    budget_encumbered_cents: int
    budget_used_cents: int
    budget_available_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RateSet(TypedDict, total=False):
    id: str
    fiscal_year: int
    effective_from: str
    lines: List[dict]
    line_verdicts: List[dict]
    status: str
    supersedes_rate_set_id: Optional[str]
    developed_by: str
    approved_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Booking(TypedDict, total=False):
    id: str
    user_id: str
    instrument_id: str
    grant_id: Optional[str]
    start_at: str
    end_at: str
    priority: str
    status: str
    cancellation_reason: Optional[str]
    penalty_cents: int
    penalty_waived: bool
    estimated_charge_cents: int
    encumbered_cents: int
    rate_set_id: Optional[str]
    applied_rate_cents_per_hour: Optional[int]
    applied_increment_minutes: Optional[int]
    applied_min_charge_minutes: Optional[int]
    created_at: str
    updated_at: str
    version: int


class UsageLog(TypedDict, total=False):
    id: str
    booking_id: str
    instrument_id: str
    user_id: str
    actual_start_at: str
    actual_end_at: str
    consumable_fee_cents: int
    status: str
    logged_by: str
    validated_by: Optional[str]
    billable_minutes: int
    usage_charge_cents: int
    created_at: str
    updated_at: str
    version: int


class RechargeBatch(TypedDict, total=False):
    id: str
    period_year: int
    period_month: int
    status: str
    entry_count: int
    gross_amount_cents: int
    subsidy_offset_cents: int
    net_amount_cents: int
    finalized_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RechargeEntry(TypedDict, total=False):
    id: str
    batch_id: str
    usage_log_id: Optional[str]
    booking_id: Optional[str]
    grant_id: Optional[str]
    user_id: str
    instrument_id: str
    kind: str
    is_external: bool
    amount_cents: int
    subsidy_offset_cents: int
    net_amount_cents: int
    status: str
    dispute_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SubsidyApplication(TypedDict, total=False):
    id: str
    user_id: str
    kind: str
    requested_amount_cents: int
    justification: str
    status: str
    reviewed_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SubsidyAward(TypedDict, total=False):
    id: str
    application_id: str
    user_id: str
    kind: str
    awarded_amount_cents: int
    remaining_amount_cents: int
    conveys_priority: bool
    valid_from: str
    valid_until: str
    status: str
    created_at: str
    updated_at: str
    version: int


class MaintenanceContract(TypedDict, total=False):
    id: str
    instrument_id: str
    vendor: str
    sla_response_hours: int
    coverage_start: str
    coverage_end: str
    annual_cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DowntimeEvent(TypedDict, total=False):
    id: str
    instrument_id: str
    maintenance_contract_id: Optional[str]
    kind: str
    start_at: str
    end_at: str
    status: str
    notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Publication(TypedDict, total=False):
    id: str
    user_id: str
    title: str
    journal: str
    published_at: str
    acknowledges_core: bool
    non_ack_reason: Optional[str]
    instrument_ids: List[str]
    status: str
    verified_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FiscalYearPeriod(TypedDict, total=False):
    id: str
    fiscal_year: int
    status: str
    carryforward_in_cents: int
    revenue_cents: int
    cash_revenue_cents: int
    cost_cents: int
    surplus_deficit_cents: int
    carryforward_out_cents: int
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
