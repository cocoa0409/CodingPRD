"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.4, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List


class ProjectStatus(str, Enum):
    PLANNING = "PLANNING"
    MOBILIZED = "MOBILIZED"
    TRENCHING = "TRENCHING"
    CONVERTING = "CONVERTING"
    RECONCILIATION = "RECONCILIATION"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class ProjectPosture(str, Enum):
    CLEAR = "CLEAR"
    CONDITIONAL = "CONDITIONAL"
    FROZEN = "FROZEN"


class ParticipationStatus(str, Enum):
    INVITED = "INVITED"
    COMMITTED = "COMMITTED"
    MOBILIZED = "MOBILIZED"
    INSTALLED = "INSTALLED"
    BILLED = "BILLED"
    SETTLED = "SETTLED"
    WITHDRAWN = "WITHDRAWN"


class UtilityType(str, Enum):
    ELECTRIC = "ELECTRIC"
    TELECOM = "TELECOM"
    CATV = "CATV"


class TrenchSegmentStatus(str, Enum):
    PLANNED = "PLANNED"
    SCHEDULED = "SCHEDULED"
    EXCAVATING = "EXCAVATING"
    BACKFILLING = "BACKFILLING"
    BACKFILLED = "BACKFILLED"
    CLOSED = "CLOSED"


class OccupancySlotStatus(str, Enum):
    RESERVED = "RESERVED"
    INSTALLING = "INSTALLING"
    INSTALL_FAILED = "INSTALL_FAILED"
    INSTALLED = "INSTALLED"
    VERIFIED = "VERIFIED"
    RELEASED = "RELEASED"


class EasementType(str, Enum):
    TRENCH = "TRENCH"
    ACCESS = "ACCESS"
    ANCHOR = "ANCHOR"


class EasementStatus(str, Enum):
    DRAFT = "DRAFT"
    REQUESTED = "REQUESTED"
    SIGNED = "SIGNED"
    RECORDED = "RECORDED"
    REFUSED = "REFUSED"


class PermitType(str, Enum):
    ENCROACHMENT = "ENCROACHMENT"
    TRAFFIC_CONTROL = "TRAFFIC_CONTROL"
    GRADING = "GRADING"


class PermitStatus(str, Enum):
    APPLICATION = "APPLICATION"
    SUBMITTED = "SUBMITTED"
    ISSUED = "ISSUED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"
    CLOSED = "CLOSED"


class WorkStatus(str, Enum):
    PLANNED = "PLANNED"
    ROUGH_IN = "ROUGH_IN"
    PANEL_SET = "PANEL_SET"
    READY_TO_ENERGIZE = "READY_TO_ENERGIZE"
    ENERGIZED = "ENERGIZED"
    INSPECTED = "INSPECTED"
    COMPLETE = "COMPLETE"


class TempServiceStatus(str, Enum):
    NONE = "NONE"
    TEMP_INSTALLED = "TEMP_INSTALLED"
    TEMP_ACTIVE = "TEMP_ACTIVE"
    TEMP_REMOVED = "TEMP_REMOVED"


class OutageWindowStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    NOTIFIED = "NOTIFIED"
    EXECUTED = "EXECUTED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class ChangeOrderStatus(str, Enum):
    PROPOSED = "PROPOSED"
    PRICED = "PRICED"
    APPROVED = "APPROVED"
    INCORPORATED = "INCORPORATED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class DelayCause(str, Enum):
    EXCUSABLE = "EXCUSABLE"
    NEGLIGENT = "NEGLIGENT"
    MIXED = "MIXED"


class CostCode(str, Enum):
    JOINT_TRENCH = "JOINT_TRENCH"
    EXCLUSIVE = "EXCLUSIVE"
    RESTORATION = "RESTORATION"
    PROGRAM_OVERHEAD = "PROGRAM_OVERHEAD"


class TrueUpRunStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"
    SETTLED = "SETTLED"


class InvoiceStatus(str, Enum):
    ISSUED = "ISSUED"
    PAID = "PAID"
    DISPUTED = "DISPUTED"
    VOID = "VOID"


class RestorationTaskType(str, Enum):
    HARDSCAPE = "HARDSCAPE"
    LANDSCAPE = "LANDSCAPE"
    IRRIGATION = "IRRIGATION"


class RestorationTaskStatus(str, Enum):
    OPEN = "OPEN"
    IN_WORK = "IN_WORK"
    COMPLETE = "COMPLETE"
    ACCEPTED = "ACCEPTED"
    WARRANTY_CLAIM = "WARRANTY_CLAIM"


class UserRole(str, Enum):
    PROGRAM_MANAGER = "ProgramManager"
    RIGHT_OF_WAY_AGENT = "RightOfWayAgent"
    UTILITY_COORDINATOR = "UtilityCoordinator"
    CONVERSION_CONTRACTOR = "ConversionContractor"
    FINANCE_ANALYST = "FinanceAnalyst"


# --- Entity TypedDicts (common_fields entities carry id/created_at/updated_at/version) ---

class Project(TypedDict, total=False):
    id: str
    name: str
    rule20_credit_cents: int
    estimated_total_cost_cents: int
    contingency_days: int
    target_cutover_on: str
    status: str
    posture: str
    cumulative_delay_days: int
    liquidated_damages_cents: int
    latest_true_up_run_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class UtilityParticipation(TypedDict, total=False):
    id: str
    project_id: str
    utility_name: str
    utility_type: str
    cost_share_bp: int
    sequence_order: int
    has_separation_waiver: bool
    status: str
    provisional_share_cents: int
    final_share_cents: Optional[int]
    variance_flag: bool
    withdrawn_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TrenchSegment(TypedDict, total=False):
    id: str
    project_id: str
    segment_code: str
    length_ft: int
    max_depth_inches: int
    parcel_ids: List[str]
    excavation_start_on: Optional[str]
    excavation_end_on: Optional[str]
    status: str
    occupied_depth_inches: int
    available_depth_inches: int
    frozen: bool
    created_at: str
    updated_at: str
    version: int


class OccupancySlot(TypedDict, total=False):
    id: str
    trench_segment_id: str
    participation_id: str
    depth_top_inches: int
    depth_bottom_inches: int
    install_start_at: str
    install_end_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Parcel(TypedDict, total=False):
    id: str
    project_id: str
    address: str
    owner_name: str
    existing_panel_amps: int
    load_calc_amps: int
    panel_upgrade_required: bool
    created_at: str
    updated_at: str
    version: int


class Easement(TypedDict, total=False):
    id: str
    parcel_id: str
    easement_type: str
    status: str
    requested_on: Optional[str]
    signed_on: Optional[str]
    recorded_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Permit(TypedDict, total=False):
    id: str
    project_id: str
    permit_type: str
    valid_from: str
    valid_to: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceConversion(TypedDict, total=False):
    id: str
    parcel_id: str
    project_id: str
    work_status: str
    temp_service_status: str
    panel_capacity_amps: Optional[int]
    last_inspection_outcome: Optional[str]
    energized_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OutageWindow(TypedDict, total=False):
    id: str
    project_id: str
    feeder_id: str
    start_at: str
    end_at: str
    conversion_ids: List[str]
    status: str
    notified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ChangeOrder(TypedDict, total=False):
    id: str
    project_id: str
    description: str
    segment_ids: List[str]
    delta_cost_cents: Optional[int]
    delta_delay_days: Optional[int]
    delay_cause: Optional[str]
    status: str
    revision_count: int
    created_at: str
    updated_at: str
    version: int


class ActualCostEntry(TypedDict, total=False):
    """Append-only ledger entry: id + created_at only — no updated_at, no version."""
    id: str
    project_id: str
    participation_id: Optional[str]
    cost_code: str
    amount_cents: int
    incurred_on: str
    submitted_by_user_id: str
    created_at: str


class TrueUpRun(TypedDict, total=False):
    id: str
    project_id: str
    status: str
    created_by_user_id: str
    published_by_user_id: Optional[str]
    total_actual_cost_cents: int
    rule20_credit_applied_cents: int
    lines: List[dict]
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict, total=False):
    id: str
    true_up_run_id: str
    participation_id: str
    principal_cents: int
    issued_on: str
    due_on: str
    status: str
    late_fee_cents: int
    amount_due_cents: int
    paid_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RestorationTask(TypedDict, total=False):
    id: str
    trench_segment_id: str
    parcel_id: str
    task_type: str
    status: str
    completed_on: Optional[str]
    accepted_on: Optional[str]
    warranty_expires_on: Optional[str]
    created_at: str
    updated_at: str
    version: int
