"""Domain types: entity TypedDicts, status enums, role enum.

Common-field branching follows PRD section 2.4: most resources carry
id + created_at + updated_at + version; LaborEntry and LedgerEntry are
append-only records that carry only id and created_at.
"""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    SERVICE_WRITER = "ServiceWriter"
    YARD_MANAGER = "YardManager"
    ENVIRONMENTAL_OFFICER = "EnvironmentalOfficer"
    ACCOUNTANT = "Accountant"
    OWNER = "Owner"


class HullType(str, Enum):
    POWER = "POWER"
    SAIL = "SAIL"


class CertificateStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"


class BillingMode(str, Enum):
    DAILY = "DAILY"
    MONTHLY_CONTRACT = "MONTHLY_CONTRACT"


class RefitJobStatus(str, Enum):
    DRAFT = "DRAFT"
    INTAKE = "INTAKE"
    HAUL_SCHEDULED = "HAUL_SCHEDULED"
    ON_HARD = "ON_HARD"
    WORK_IN_PROGRESS = "WORK_IN_PROGRESS"
    READY_FOR_SPLASH = "READY_FOR_SPLASH"
    AWAITING_TRIAL = "AWAITING_TRIAL"
    COMPLETE = "COMPLETE"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class LiftSlotKind(str, Enum):
    HAUL_OUT = "HAUL_OUT"
    SPLASH = "SPLASH"


class LiftSlotStatus(str, Enum):
    BOOKED = "BOOKED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class StandAssignmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


class WorkOrderType(str, Enum):
    BOTTOM_PAINT = "BOTTOM_PAINT"
    MECHANICAL = "MECHANICAL"
    ELECTRICAL = "ELECTRICAL"
    RIGGING = "RIGGING"
    FIBERGLASS = "FIBERGLASS"
    WINTERIZATION = "WINTERIZATION"
    SHRINK_WRAP = "SHRINK_WRAP"


class WorkOrderStatus(str, Enum):
    ESTIMATE = "ESTIMATE"
    APPROVED = "APPROVED"
    IN_PROGRESS = "IN_PROGRESS"
    ON_HOLD = "ON_HOLD"
    CHANGE_REQUESTED = "CHANGE_REQUESTED"
    COMPLETE = "COMPLETE"
    CANCELLED = "CANCELLED"


class WorkerType(str, Enum):
    YARD_CREW = "YARD_CREW"
    SUBCONTRACTOR = "SUBCONTRACTOR"


class PartCategory(str, Enum):
    BOTTOM_PAINT = "BOTTOM_PAINT"
    MECHANICAL = "MECHANICAL"
    ELECTRICAL = "ELECTRICAL"
    RIGGING = "RIGGING"
    OTHER = "OTHER"


class PartStatus(str, Enum):
    EXPECTED = "EXPECTED"
    RECEIVED = "RECEIVED"
    REJECTED = "REJECTED"


class EnvironmentalEventKind(str, Enum):
    WASHDOWN = "WASHDOWN"
    SANDING = "SANDING"
    PAINT_SPRAY = "PAINT_SPRAY"


class EnvironmentalEventStatus(str, Enum):
    LOGGED = "LOGGED"
    ADVISORY = "ADVISORY"
    VIOLATION_FLAGGED = "VIOLATION_FLAGGED"
    REMEDIATED = "REMEDIATED"


class HoldKind(str, Enum):
    ENVIRONMENTAL = "ENVIRONMENTAL"
    PAYMENT = "PAYMENT"


class HoldSource(str, Enum):
    MANUAL = "MANUAL"
    AUTO_VIOLATION = "AUTO_VIOLATION"


class HoldStatus(str, Enum):
    OPEN = "OPEN"
    RELEASED = "RELEASED"


class LedgerEntryKind(str, Enum):
    PAYMENT = "PAYMENT"
    CREDIT = "CREDIT"
    DEPOSIT = "DEPOSIT"
    CHARGE = "CHARGE"


class LedgerEntryCategory(str, Enum):
    STORAGE = "STORAGE"
    LABOR = "LABOR"
    PARTS_HANDLING = "PARTS_HANDLING"
    OTHER = "OTHER"


class LedgerEntryStatus(str, Enum):
    POSTED = "POSTED"
    VOIDED = "VOIDED"


class SeaTrialOutcome(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class PartInspectOutcome(str, Enum):
    RECEIVED = "RECEIVED"
    REJECTED = "REJECTED"


class Vessel(TypedDict, total=False):
    id: str
    name: str
    owner_name: str
    owner_user_id: str
    loa_ft: float
    beam_ft: float
    hull_type: str
    displacement_tons: float
    created_at: str
    updated_at: str
    version: int


class InsuranceCertificate(TypedDict, total=False):
    id: str
    vessel_id: str
    provider: str
    policy_no: str
    liability_coverage_cents: int
    effective_date: str
    expiry_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RefitJob(TypedDict, total=False):
    id: str
    vessel_id: str
    billing_mode: str
    scope_notes: Optional[str]
    status: str
    hauled_at: Optional[str]
    splashed_at: Optional[str]
    lay_days: int
    last_accrual_date: Optional[str]
    open_hold_count: int
    completed_at: Optional[str]
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LiftSlot(TypedDict, total=False):
    id: str
    job_id: str
    kind: str
    scheduled_start: str
    scheduled_end: str
    vessel_displacement_tons: float
    status: str
    created_at: str
    updated_at: str
    version: int


class YardRow(TypedDict, total=False):
    id: str
    code: str
    total_stands: int
    stands_in_use: int
    created_at: str
    updated_at: str
    version: int


class StandAssignment(TypedDict, total=False):
    id: str
    row_id: str
    job_id: str
    stands_used: int
    start_date: str
    end_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class WorkOrder(TypedDict, total=False):
    id: str
    job_id: str
    type: str
    description: str
    quoted_hours: float
    quoted_rate_cents: int
    quoted_parts_cents: int
    quoted_total_cents: int
    actual_cost_cents: int
    revision: int
    change_note: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class LaborEntry(TypedDict, total=False):
    # Append-only record (PRD section 2.4): id + created_at only,
    # no updated_at and no version.
    id: str
    work_order_id: str
    worker_type: str
    hours: float
    rate_cents: int
    subcontractor_name: Optional[str]
    line_cost_cents: int
    created_at: str


class Part(TypedDict, total=False):
    id: str
    job_id: str
    description: str
    category: str
    owner_supplied: bool
    declared_value_cents: int
    status: str
    inspect_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EnvironmentalEvent(TypedDict, total=False):
    id: str
    job_id: str
    kind: str
    containment_used: bool
    runoff_tss_ppm: float
    occurred_at: str
    status: str
    remediation_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ComplianceHold(TypedDict, total=False):
    id: str
    job_id: str
    kind: str
    note: str
    source: str
    source_event_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class LedgerEntry(TypedDict, total=False):
    # Append-only record (PRD section 2.4): id + created_at only,
    # no updated_at and no version.
    id: str
    job_id: str
    kind: str
    category: str
    amount_cents: int
    memo: Optional[str]
    status: str
    source_work_order_id: Optional[str]
    source_part_id: Optional[str]
    created_at: str


class Statement(TypedDict, total=False):
    job_id: str
    billing_mode: str
    status: str
    lay_days: int
    storage_charges_cents: int
    labor_charges_cents: int
    parts_handling_charges_cents: int
    total_charges_cents: int
    payments_cents: int
    credits_cents: int
    deposits_cents: int
    balance_cents: int
    required_deposit_cents: int
    deposit_satisfied: bool
