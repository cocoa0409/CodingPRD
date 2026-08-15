"""Domain types: entity TypedDicts, status enums, role enum.

All field names and enum spellings follow the PRD exactly (see PRD sections
2.1, 2.4, and 3.1-3.9).
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# --- Roles (PRD section 2.1) ---

class UserRole(str, Enum):
    PROJECT_MANAGER = "ProjectManager"
    SITE_SUPERVISOR = "SiteSupervisor"
    SAFETY_OFFICER = "SafetyOfficer"
    PAYROLL_CLERK = "PayrollClerk"
    CUSTOMER_REP = "CustomerRep"


# --- Project enums (PRD section 3.1) ---

class BillingMode(str, Enum):
    TM = "TM"
    LUMP_SUM = "LUMP_SUM"


class OtBasis(str, Enum):
    DAILY_OT = "DAILY_OT"
    WEEKLY_OT = "WEEKLY_OT"


class WorkStatus(str, Enum):
    AWARDED = "AWARDED"
    MOBILIZED = "MOBILIZED"
    INSTALLING = "INSTALLING"
    COMMISSIONING = "COMMISSIONING"
    COMPLETED = "COMPLETED"


class HoldStatus(str, Enum):
    CLEAR = "CLEAR"
    SAFETY_HOLD = "SAFETY_HOLD"


# --- Site survey (PRD section 3.2) ---

class SiteSurveyStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


# --- Safety plan (PRD section 3.3) ---

class SafetyPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


# --- Lockout window (PRD section 3.3) ---

class LockoutWindowStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


# --- Rigging plan (PRD section 3.4) ---

class RiggingConfig(str, Enum):
    SINGLE_CRANE = "SINGLE_CRANE"
    TANDEM = "TANDEM"
    GANTRY = "GANTRY"


class RiggingPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


# --- Lift permit (PRD section 3.5) ---

class LiftPermitStatus(str, Enum):
    ISSUED = "ISSUED"
    EXECUTED = "EXECUTED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


# --- Alignment record (PRD section 3.6) ---

class ToleranceClass(str, Enum):
    STANDARD = "STANDARD"
    PRECISION = "PRECISION"


class AlignmentVerdict(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class AlignmentRecordStatus(str, Enum):
    RECORDED = "RECORDED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


# --- Commissioning checklist (PRD section 3.7) ---

class ChecklistStatus(str, Enum):
    IN_PROGRESS = "IN_PROGRESS"
    SUBMITTED = "SUBMITTED"
    SIGNED_OFF = "SIGNED_OFF"


# --- Labor entry (PRD section 3.8) ---

class LaborClassification(str, Enum):
    MW_JOURNEYMAN = "MW_JOURNEYMAN"
    MW_APPRENTICE = "MW_APPRENTICE"
    MW_FOREMAN = "MW_FOREMAN"
    OPERATOR = "OPERATOR"


class Shift(str, Enum):
    DAY = "DAY"
    NIGHT = "NIGHT"


class LaborEntryStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    INVOICED = "INVOICED"


# --- Invoice (PRD section 3.9) ---

class InvoiceKind(str, Enum):
    PROGRESS = "PROGRESS"
    FINAL = "FINAL"


# --- Review outcomes ---

class ReviewOutcome(str, Enum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    APPROVED = "APPROVED"


# --- Entity TypedDicts ---
# Primary resources carry id, created_at, updated_at, version (PRD section 2.4).
# Invoice is append-only: id and created_at only (PRD section 2.4).

class Project(TypedDict):
    id: str
    name: str
    customer_name: str
    site_address: str
    billing_mode: str
    contract_amount_cents: int
    equipment_hourly_rate_cents: int
    retainage_pct: float
    ot_basis: str
    work_status: str
    hold_status: str
    approved_rigging_plan_id: Optional[str]
    approved_rigging_plan_revision: Optional[int]
    approved_labor_cents: int
    approved_equipment_cents: int
    invoiced_cents: int
    created_at: str
    updated_at: str
    version: int


class SiteSurvey(TypedDict):
    id: str
    project_id: str
    survey_date: str
    anchor_bolt_count: int
    anchor_tolerance_mm: float
    anchor_measured_max_deviation_mm: float
    overhead_clearance_mm: float
    foundation_pour_date: str
    anchor_check_passed: bool
    foundation_cured: bool
    status: str
    reviewer_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SafetyPlan(TypedDict):
    id: str
    project_id: str
    plan_document_ref: str
    loto_procedure_ref: str
    status: str
    created_at: str
    updated_at: str
    version: int


class LockoutWindow(TypedDict):
    id: str
    project_id: str
    feeder_id: str
    starts_at: str
    ends_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RiggingPlan(TypedDict):
    id: str
    project_id: str
    revision: int
    lift_weight_tons: float
    crane_model: str
    planned_crane_capacity_tons: float
    rigging_config: str
    weight_check_passed: bool
    status: str
    reviewer_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LiftPermit(TypedDict):
    id: str
    project_id: str
    crane_ref: str
    lift_starts_at: str
    lift_ends_at: str
    road_permit_required: bool
    road_permit_number: Optional[str]
    duration_hours: float
    equipment_charge_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class AlignmentRecord(TypedDict):
    id: str
    project_id: str
    measurement_point: str
    tolerance_class: str
    measured_offset_mils: float
    measured_angular_mils_per_in: float
    offset_passed: bool
    angular_passed: bool
    verdict: str
    status: str
    reviewer_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ChecklistItem(TypedDict):
    item_key: str
    description: str
    required: bool
    checked: bool
    checked_by_user_id: Optional[str]
    checked_at: Optional[str]


class CommissioningChecklist(TypedDict):
    id: str
    project_id: str
    items: List[Dict[str, Any]]
    required_count: int
    checked_required_count: int
    status: str
    signed_off_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LaborEntry(TypedDict):
    id: str
    project_id: str
    worker_ref: str
    classification: str
    work_date: str
    hours_worked: float
    shift: str
    regular_hours: float
    overtime_hours: float
    base_rate_cents: int
    total_cost_cents: int
    status: str
    submitted_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    # Append-only financial record: carries id and created_at only,
    # never updated after creation, exposes neither updated_at nor version.
    id: str
    project_id: str
    kind: str
    period_start: str
    period_end: str
    billing_mode_snapshot: str
    gross_cents: int
    retainage_cents: int
    retainage_released_cents: int
    amount_cents: int
    labor_entry_ids: List[str]
    lift_permit_ids: List[str]
    created_at: str
