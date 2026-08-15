"""Domain types: entity TypedDicts, status enums, role enum.

All ten resources carry the same four system-managed properties (id,
created_at, updated_at, version) per the PRD's common-resource contract.
"""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    SCHEDULER_ADMIN = "SchedulerAdmin"
    CHIEF_OF_STAFF = "ChiefOfStaff"
    PHYSICIAN = "Physician"
    CREDENTIALING_OFFICER = "CredentialingOfficer"


class CallProgramStatus(str, Enum):
    DRAFT = "DRAFT"
    GENERATED = "GENERATED"
    PUBLISHED = "PUBLISHED"
    RECONCILED = "RECONCILED"


class EmploymentType(str, Enum):
    STAFF = "STAFF"
    LOCUM = "LOCUM"


class PhysicianStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class WindowKind(str, Enum):
    VACATION = "VACATION"
    CME = "CME"
    PERSONAL = "PERSONAL"


class WindowStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    CANCELLED = "CANCELLED"


class CallType(str, Enum):
    PRIMARY = "PRIMARY"
    BACKUP = "BACKUP"


class DateType(str, Enum):
    WEEKDAY = "WEEKDAY"
    WEEKEND = "WEEKEND"
    HOLIDAY = "HOLIDAY"


class SlotStatus(str, Enum):
    OPEN = "OPEN"
    ASSIGNED = "ASSIGNED"
    COVERED = "COVERED"
    UNCOVERED = "UNCOVERED"


class AssignmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVATED = "ACTIVATED"
    SERVED = "SERVED"
    SWAPPED = "SWAPPED"
    CANCELLED = "CANCELLED"


class AssignmentOrigin(str, Enum):
    GENERATED = "GENERATED"
    MANUAL = "MANUAL"
    SWAP = "SWAP"
    LOCUM_FILL = "LOCUM_FILL"


class SwapStatus(str, Enum):
    POSTED = "POSTED"
    CLAIMED = "CLAIMED"
    APPROVED = "APPROVED"
    EXECUTED = "EXECUTED"
    CANCELLED = "CANCELLED"


class GapReason(str, Enum):
    GENERATION_SHORTFALL = "GENERATION_SHORTFALL"
    ASSIGNMENT_CANCELLED = "ASSIGNMENT_CANCELLED"
    PHYSICIAN_DEACTIVATED = "PHYSICIAN_DEACTIVATED"


class GapStatus(str, Enum):
    OPEN = "OPEN"
    REQUISITIONED = "REQUISITIONED"
    RESOLVED = "RESOLVED"


class RequisitionStatus(str, Enum):
    OPEN = "OPEN"
    SOURCED = "SOURCED"
    CREDENTIALING = "CREDENTIALING"
    READY = "READY"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"


class CaseStatus(str, Enum):
    INITIATED = "INITIATED"
    IN_PROGRESS = "IN_PROGRESS"
    CLEARED = "CLEARED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class CredentialingItem(str, Enum):
    LICENSE_VERIFICATION = "license_verification"
    MALPRACTICE_VERIFICATION = "malpractice_verification"
    PRIVILEGES_GRANTING = "privileges_granting"
    HEALTH_SCREENING = "health_screening"
    ORIENTATION = "orientation"


class PayEntryStatus(str, Enum):
    ACCRUED = "ACCRUED"
    FINALIZED = "FINALIZED"


class CallProgram(TypedDict, total=False):
    id: str
    name: str
    service_line: str
    period_start: str
    period_end: str
    holiday_dates: list
    weekday_primary_required: int
    weekend_primary_required: int
    holiday_primary_required: int
    weekday_backup_required: int
    weekend_backup_required: int
    holiday_backup_required: int
    swap_cutoff_hours: int
    credentialing_lead_hours: int
    equity_band_points: float
    payroll_budget_cents: int
    primary_rate_cents: int
    backup_rate_cents: int
    weekend_multiplier: float
    holiday_multiplier: float
    backup_activation_multiplier: float
    moonlight_premium_multiplier: float
    moonlight_premium_threshold_hours: int
    weekday_call_points: float
    weekend_call_points: float
    holiday_call_points: float
    backup_point_multiplier: float
    payroll_reserved_cents: int
    payroll_accrued_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Physician(TypedDict, total=False):
    id: str
    full_name: str
    specialty: str
    employment_type: str
    moonlight_cap_hours: int
    status: str
    created_at: str
    updated_at: str
    version: int


class UnavailabilityWindow(TypedDict, total=False):
    id: str
    physician_id: str
    start_date: str
    end_date: str
    kind: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CallSlot(TypedDict, total=False):
    id: str
    program_id: str
    date: str
    call_type: str
    position_index: int
    date_type: str
    window_start: str
    window_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CallAssignment(TypedDict, total=False):
    id: str
    slot_id: str
    physician_id: str
    program_id: str
    origin: str
    source_swap_id: Optional[str]
    source_requisition_id: Optional[str]
    call_hours: int
    projected_pay_cents: int
    status: str
    activated_at: Optional[str]
    served_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SwapRequest(TypedDict, total=False):
    id: str
    program_id: str
    assignment_id: str
    offerer_physician_id: str
    claimant_physician_id: Optional[str]
    decline_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CoverageGap(TypedDict, total=False):
    id: str
    program_id: str
    slot_id: str
    reason: str
    detected_at: str
    resolved_by_assignment_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class LocumRequisition(TypedDict, total=False):
    id: str
    gap_id: str
    program_id: str
    candidate_physician_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CredentialingCase(TypedDict, total=False):
    id: str
    requisition_id: str
    locum_physician_id: str
    clear_by: str
    items: dict
    status: str
    created_at: str
    updated_at: str
    version: int


class PayEntry(TypedDict, total=False):
    id: str
    assignment_id: str
    physician_id: str
    program_id: str
    slot_date: str
    call_type: str
    date_type: str
    base_rate_cents: int
    activation_applied: bool
    premium_applied: bool
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
