"""Domain types: entity TypedDicts, status enums, role enum.

All entities in the VMS are mutable record types, so every entity carries
id, created_at, updated_at, and version (PRD §2.4).
"""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    PROGRAM_MANAGER = "ProgramManager"
    HIRING_MANAGER = "HiringManager"
    SUPPLIER = "Supplier"
    FINANCE = "Finance"


class ProgramStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class SupplierStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class TenureStatus(str, Enum):
    CLEAR = "CLEAR"
    WARNING = "WARNING"
    BREACH = "BREACH"


class RequisitionStatus(str, Enum):
    DRAFT = "DRAFT"
    DISTRIBUTED = "DISTRIBUTED"
    FILLED = "FILLED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class DistributionStatus(str, Enum):
    PENDING = "PENDING"
    RELEASED = "RELEASED"
    REVOKED = "REVOKED"


class SubmittalStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    SHORTLISTED = "SHORTLISTED"
    INTERVIEWING = "INTERVIEWING"
    RATE_PROPOSED = "RATE_PROPOSED"
    OFFERED = "OFFERED"
    HIRED = "HIRED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class EngagementStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ON_HOLD = "ON_HOLD"
    ENDED = "ENDED"


class ComplianceStatus(str, Enum):
    CLEAR = "CLEAR"
    TENURE_WARNING = "TENURE_WARNING"
    TENURE_BREACH = "TENURE_BREACH"


class StatementOfWorkStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class MilestoneStatus(str, Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    INVOICED = "INVOICED"


class TimesheetStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    INVOICED = "INVOICED"


class ExpenseStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    INVOICED = "INVOICED"


class ExpenseCategory(str, Enum):
    TRAVEL = "TRAVEL"
    LODGING = "LODGING"
    MEALS = "MEALS"
    EQUIPMENT = "EQUIPMENT"
    OTHER = "OTHER"


# --- Entity TypedDicts (all common_fields: true -> id/created_at/updated_at/version) ---

class Program(TypedDict):
    id: str
    name: str
    client_name: str
    default_markup_pct: float
    max_markup_pct: float
    coemployment_tenure_limit_days: int
    tenure_warning_threshold_days: int
    timesheet_approval_window_days: int
    current_clock: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Supplier(TypedDict):
    id: str
    program_id: str
    name: str
    tier: int
    status: str
    created_at: str
    updated_at: str
    version: int


class WorkerProfile(TypedDict):
    id: str
    program_id: str
    full_name: str
    national_id_hash: str
    cumulative_engaged_days: int
    tenure_status: str
    created_at: str
    updated_at: str
    version: int


class Requisition(TypedDict):
    id: str
    program_id: str
    title: str
    openings: int
    filled_count: int
    max_pay_rate_cents: int
    tier_release_interval_hours: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Distribution(TypedDict):
    id: str
    requisition_id: str
    supplier_id: str
    tier_at_distribution: int
    released_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Submittal(TypedDict):
    id: str
    requisition_id: str
    supplier_id: str
    worker_profile_id: str
    pay_rate_cents: int
    bill_rate_cents: int
    effective_markup_pct: float
    rounds: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Assignment(TypedDict):
    id: str
    program_id: str
    submittal_id: str
    worker_profile_id: str
    pay_rate_cents: int
    bill_rate_cents: int
    start_date: str
    planned_end_date: str
    actual_end_date: Optional[str]
    engaged_days: int
    engagement_status: str
    compliance_status: str
    created_at: str
    updated_at: str
    version: int


class StatementOfWork(TypedDict):
    id: str
    program_id: str
    supplier_id: str
    title: str
    total_value_cents: int
    invoiced_value_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Milestone(TypedDict):
    id: str
    statement_of_work_id: str
    name: str
    milestone_amount_cents: int
    sequence: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Timesheet(TypedDict):
    id: str
    assignment_id: str
    week_start_date: str
    regular_hours: float
    overtime_hours: float
    submitted_at: Optional[str]
    bill_amount_cents: int
    pay_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Expense(TypedDict):
    id: str
    assignment_id: str
    category: str
    amount_cents: int
    billable: bool
    reimbursable_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
