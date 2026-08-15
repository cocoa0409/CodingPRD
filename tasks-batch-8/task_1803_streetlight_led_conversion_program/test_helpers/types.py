"""Domain types: entity TypedDicts, status enums, role enum.

All entity types in this PRD carry the full common-field set
(id, created_at, updated_at, version) per PRD section 2.4.
"""
from enum import Enum
from typing import Optional, TypedDict


class ProgramStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class Zone(str, Enum):
    RESIDENTIAL = "RESIDENTIAL"
    ARTERIAL = "ARTERIAL"
    DOWNTOWN = "DOWNTOWN"
    RURAL = "RURAL"


class PoleStatus(str, Enum):
    SURVEYED = "SURVEYED"
    AUDIT_CLEARED = "AUDIT_CLEARED"
    SCHEDULED = "SCHEDULED"
    CONVERTED = "CONVERTED"
    REWORK = "REWORK"
    VERIFIED = "VERIFIED"
    UNDER_REPAIR = "UNDER_REPAIR"
    EXEMPT = "EXEMPT"


class OwnershipType(str, Enum):
    MUNICIPAL = "MUNICIPAL"
    UTILITY_OWNED = "UTILITY_OWNED"


class FixtureClass(str, Enum):
    COBRA_HEAD = "COBRA_HEAD"
    FLOOD = "FLOOD"
    POST_TOP = "POST_TOP"
    DECORATIVE = "DECORATIVE"


class WattageTier(str, Enum):
    T1 = "T1"
    T2 = "T2"
    T3 = "T3"
    T4 = "T4"
    T5 = "T5"


class AuditStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    DISPUTED = "DISPUTED"
    SUPERSEDED = "SUPERSEDED"


class RouteStatus(str, Enum):
    PLANNED = "PLANNED"
    RELEASED = "RELEASED"
    IN_PROGRESS = "IN_PROGRESS"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class StopStatus(str, Enum):
    PENDING = "PENDING"
    COMPLETE = "COMPLETE"
    SKIPPED = "SKIPPED"
    BLOCKED = "BLOCKED"


class DifficultyClass(str, Enum):
    STANDARD = "STANDARD"
    HEAVY = "HEAVY"
    COMPLEX = "COMPLEX"


class WorkOrderExecutionStatus(str, Enum):
    PENDING = "PENDING"
    DISPATCHED = "DISPATCHED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    REWORK_PENDING = "REWORK_PENDING"
    CANCELLED = "CANCELLED"


class WorkOrderQcStatus(str, Enum):
    NONE = "NONE"
    AWAITING_QC = "AWAITING_QC"
    QC_PASSED = "QC_PASSED"
    QC_FAILED = "QC_FAILED"


class Shielding(str, Enum):
    FULL_CUTOFF = "FULL_CUTOFF"
    SEMI_CUTOFF = "SEMI_CUTOFF"
    NONE = "NONE"


class RateScheduleStatus(str, Enum):
    DRAFT = "DRAFT"
    FILED = "FILED"
    EFFECTIVE = "EFFECTIVE"
    SUPERSEDED = "SUPERSEDED"


class AccountStatus(str, Enum):
    OPEN = "OPEN"
    FROZEN = "FROZEN"


class BillingLineStatus(str, Enum):
    ESTIMATED = "ESTIMATED"
    BILLED = "BILLED"
    SUPERSEDED = "SUPERSEDED"


class BillingLineType(str, Enum):
    REGULAR = "REGULAR"
    ADJUSTMENT = "ADJUSTMENT"


class TicketStatus(str, Enum):
    OPEN = "OPEN"
    TRIAGED = "TRIAGED"
    DISPATCHED = "DISPATCHED"
    RESOLVED = "RESOLVED"
    VERIFIED = "VERIFIED"
    REOPENED = "REOPENED"
    DUPLICATE = "DUPLICATE"


class TicketPriority(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    STANDARD = "STANDARD"


class ResolutionCode(str, Enum):
    LIGHT_OUT_FIXED = "LIGHT_OUT_FIXED"
    FIXTURE_REPLACED = "FIXTURE_REPLACED"
    NO_FAULT_FOUND = "NO_FAULT_FOUND"


class SalvageBatchStatus(str, Enum):
    ACCUMULATING = "ACCUMULATING"
    SEALED = "SEALED"
    MANIFESTED = "MANIFESTED"
    SETTLED = "SETTLED"
    REJECTED = "REJECTED"


class ReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ATTESTED = "ATTESTED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class ReportMethod(str, Enum):
    ENGINEERING_ESTIMATE = "ENGINEERING_ESTIMATE"
    METERED_ACTUAL = "METERED_ACTUAL"


class ExceptionKind(str, Enum):
    CCT_WAIVER = "CCT_WAIVER"
    CONVERSION_EXEMPTION = "CONVERSION_EXEMPTION"


class ExceptionStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"


class UserRole(str, Enum):
    PROGRAM_MANAGER = "ProgramManager"
    FIELD_SUPERVISOR = "FieldSupervisor"
    QA_INSPECTOR = "QaInspector"
    BILLING_ANALYST = "BillingAnalyst"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    CITIZEN_REPORTER = "CitizenReporter"
    AUDITOR = "Auditor"


class ConversionProgram(TypedDict):
    id: str
    program_name: str
    program_budget_cents: int
    fy_rebate_cap_cents: int
    rebate_cents_per_kwh: int
    budget_balance_cents: int
    current_billing_run_estimated_cents: int
    converted_pole_count: int
    pending_salvage_item_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceDistrict(TypedDict):
    id: str
    program_id: str
    district_name: str
    zone: str
    cct_cap_kelvin: int
    full_cutoff_required: bool
    created_at: str
    updated_at: str
    version: int


class Pole(TypedDict):
    id: str
    district_id: str
    pole_number: str
    ownership_type: str
    fixture_class: str
    nameplate_wattage: int
    effective_wattage: int
    pre_conversion_wattage: Optional[int]
    led_wattage: Optional[int]
    led_in_service_date: Optional[str]
    billing_wattage: int
    wattage_tier: str
    pre_repair_status: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class WattageAudit(TypedDict):
    id: str
    pole_id: str
    audited_wattage: int
    auditor_notes: str
    revision_count: int
    decided_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Crew(TypedDict):
    id: str
    program_id: str
    crew_name: str
    base_stops_per_shift: int
    hourly_rate_cents: int
    created_at: str
    updated_at: str
    version: int


class ConversionRoute(TypedDict):
    id: str
    district_id: str
    crew_id: str
    window_start_date: str
    window_end_date: str
    traffic_control_required: bool
    stop_count: int
    blocked_stop_count: int
    total_workload_minutes: int
    required_shifts: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RouteStop(TypedDict):
    id: str
    route_id: str
    pole_id: str
    sequence_number: int
    difficulty_class: str
    stop_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class WorkOrder(TypedDict):
    id: str
    route_id: Optional[str]
    stop_id: Optional[str]
    pole_id: str
    crew_id: str
    ticket_id: Optional[str]
    is_replacement: bool
    stop_minutes: int
    new_fixture_wattage: Optional[int]
    new_cct_kelvin: Optional[int]
    shielding: Optional[str]
    estimated_labor_cost_cents: int
    est_reconciled: bool
    cumulative_week_minutes_before: Optional[int]
    overtime_minutes: Optional[int]
    labor_cost_cents: Optional[int]
    performed_by_user_id: Optional[str]
    qc_by_user_id: Optional[str]
    completed_at: Optional[str]
    execution_status: str
    qc_status: str
    created_at: str
    updated_at: str
    version: int


class TariffRateSchedule(TypedDict):
    id: str
    program_id: str
    ownership_class: str
    effective_from: str
    effective_until: Optional[str]
    tier_rates: dict
    status: str
    created_at: str
    updated_at: str
    version: int


class TariffAccount(TypedDict):
    id: str
    district_id: str
    account_number: str
    ownership_class: str
    current_period: str
    current_period_estimated_cents: int
    ytd_billed_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class BillingLine(TypedDict):
    id: str
    account_id: str
    pole_id: str
    rate_schedule_id: str
    period: str
    line_type: str
    billing_wattage: int
    tier: str
    charge_cents: int
    supersedes_line_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class OutageTicket(TypedDict):
    id: str
    pole_id: str
    reporter_user_id: str
    description: str
    hazard_flag: bool
    duplicate_of_ticket_id: Optional[str]
    priority: Optional[str]
    sla_hours: Optional[int]
    sla_breached: Optional[bool]
    assigned_crew_id: Optional[str]
    reported_at: str
    resolved_at: Optional[str]
    resolution_code: Optional[str]
    reopen_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SalvageBatch(TypedDict):
    id: str
    program_id: str
    batch_label: str
    contaminated_flag: Optional[bool]
    item_count: int
    total_weight_lbs: float
    settlement_value_cents: Optional[int]
    manifest_code: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class SalvageItem(TypedDict):
    id: str
    batch_id: Optional[str]
    pole_id: str
    fixture_class: str
    weight_lbs: float
    mercury_flag: bool
    created_at: str
    updated_at: str
    version: int


class SavingsReport(TypedDict):
    id: str
    program_id: str
    period: str
    method: str
    fiscal_year_label: str
    baseline_kwh: float
    actual_kwh: float
    savings_kwh: float
    raw_credit_cents: int
    attested_credit_cents: Optional[int]
    submitted_by_user_id: Optional[str]
    attested_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ComplianceException(TypedDict):
    id: str
    pole_id: str
    exception_kind: str
    requested_cct_kelvin: Optional[int]
    valid_until: str
    decided_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
