"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List, Any


# ---------------------------------------------------------------------------
# Role enum (PRD §2.1)
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    PROGRAM_ADMIN = "ProgramAdmin"
    FIELD_OPERATOR = "FieldOperator"
    UTILITY_SUPERVISOR = "UtilitySupervisor"
    FIRE_DEPT_LIAISON = "FireDeptLiaison"
    PRIVATE_OWNER_REP = "PrivateOwnerRep"


# ---------------------------------------------------------------------------
# Status enums (PRD §3)
# ---------------------------------------------------------------------------

class ProgramStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class Season(str, Enum):
    SPRING = "SPRING"
    FALL = "FALL"


class HydrantStatus(str, Enum):
    IN_SERVICE = "IN_SERVICE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"
    DECOMMISSIONED = "DECOMMISSIONED"


class Ownership(str, Enum):
    MUNICIPAL = "MUNICIPAL"
    PRIVATE = "PRIVATE"


class InspectionTier(str, Enum):
    CURRENT = "CURRENT"
    DUE_SOON = "DUE_SOON"
    OVERDUE = "OVERDUE"
    CRITICAL = "CRITICAL"


class InspectionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class InspectionResult(str, Enum):
    NONE = "NONE"
    PASS = "PASS"
    FAIL = "FAIL"


class FlowTestStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    RESULTS_SUBMITTED = "RESULTS_SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    MISSED = "MISSED"


class FlowClassification(str, Enum):
    NONE = "NONE"
    PASS = "PASS"
    FAIL = "FAIL"


class CancelReason(str, Enum):
    OPERATOR_CANCEL = "OPERATOR_CANCEL"
    OUTAGE_AUTO_CANCEL = "OUTAGE_AUTO_CANCEL"


class FlushSequenceStatus(str, Enum):
    PLANNED = "PLANNED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"


class FlushOrigin(str, Enum):
    SCHEDULED_PROGRAM = "SCHEDULED_PROGRAM"
    COMPLAINT_AUTO = "COMPLAINT_AUTO"


class StepAction(str, Enum):
    OPEN = "OPEN"
    CLOSE = "CLOSE"


class StepStatus(str, Enum):
    PENDING = "PENDING"
    EXECUTED = "EXECUTED"


class ComplaintCategory(str, Enum):
    DISCOLORED_WATER = "DISCOLORED_WATER"
    ODOR = "ODOR"
    TASTE = "TASTE"
    PRESSURE = "PRESSURE"


class ComplaintStatus(str, Enum):
    OPEN = "OPEN"
    LINKED = "LINKED"
    RESOLVED = "RESOLVED"
    DISMISSED = "DISMISSED"


class OutageReason(str, Enum):
    VALVE_FAILURE = "VALVE_FAILURE"
    LEAK = "LEAK"
    DAMAGE = "DAMAGE"
    OTHER = "OTHER"


class OutageStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class NotificationStatus(str, Enum):
    PENDING = "PENDING"
    ACKNOWLEDGED = "ACKNOWLEDGED"


class WorkOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class PartLineStatus(str, Enum):
    PENDING = "PENDING"
    RESERVED = "RESERVED"
    CONSUMED = "CONSUMED"
    RELEASED = "RELEASED"


class WeightingProfile(str, Enum):
    MUNICIPAL_ONLY = "MUNICIPAL_ONLY"
    ALL_HYDRANTS_HALF_PRIVATE = "ALL_HYDRANTS_HALF_PRIVATE"


class SnapshotStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


# ---------------------------------------------------------------------------
# Entity TypedDicts (PRD §2.4: every entity carries the full common set —
# id, created_at, updated_at, version)
# ---------------------------------------------------------------------------

class FlushingProgram(TypedDict, total=False):
    id: str
    program_year: int
    season: str
    status: str
    hydrants_out_of_service_count: int
    unacknowledged_notification_count: int
    created_at: str
    updated_at: str
    version: int


class PressureZone(TypedDict, total=False):
    id: str
    name: str
    cooldown_minutes: int
    created_at: str
    updated_at: str
    version: int


class PrivateOwner(TypedDict, total=False):
    id: str
    name: str
    contact_email: str
    created_at: str
    updated_at: str
    version: int


class Hydrant(TypedDict, total=False):
    id: str
    hydrant_number: str
    program_id: str
    zone_id: str
    ownership: str
    private_owner_id: Optional[str]
    required_fire_flow_gpm: int
    outlet_diameter_in: float
    discharge_coefficient: float
    status: str
    active_outage_id: Optional[str]
    latest_inspection_id: Optional[str]
    last_verified_inspection_date: Optional[str]
    inspection_tier: str
    provisional_fire_flow_gpm: Optional[int]
    approved_fire_flow_gpm: Optional[int]
    targeted_flush_pending: bool
    created_at: str
    updated_at: str
    version: int


class Inspection(TypedDict, total=False):
    id: str
    hydrant_id: str
    scheduled_date: str
    status: str
    performed_date: Optional[str]
    defects_found: Optional[bool]
    condition_notes: str
    performed_by_user_id: Optional[str]
    verified_by_user_id: Optional[str]
    result: str
    created_at: str
    updated_at: str
    version: int


class FlowTest(TypedDict, total=False):
    id: str
    hydrant_id: str
    window_start: str
    window_end: str
    status: str
    static_psi: Optional[float]
    residual_psi: Optional[float]
    pitot_psi: Optional[float]
    pitot_flow_gpm: Optional[float]
    flow_at_20psi_gpm: Optional[int]
    classification: str
    recorded_by_user_id: Optional[str]
    reviewed_by_user_id: Optional[str]
    cancel_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FlushStep(TypedDict, total=False):
    step_index: int
    valve_tag: str
    action: str
    status: str
    executed_at: Optional[str]
    executed_by_user_id: Optional[str]
    flow_gpm: Optional[float]
    duration_minutes: Optional[float]


class FlushSequence(TypedDict, total=False):
    id: str
    program_id: str
    zone_id: str
    hydrant_id: str
    origin: str
    status: str
    window_start: str
    window_end: str
    steps: List[FlushStep]
    source_chlorine_residual_mg_L: Optional[float]
    total_flushed_gallons: Optional[int]
    dechlorination_tablets_required: Optional[int]
    final_discharge_residual_mg_L: Optional[float]
    created_at: str
    updated_at: str
    version: int


class WaterQualityComplaint(TypedDict, total=False):
    id: str
    hydrant_id: str
    category: str
    description: str
    status: str
    flush_sequence_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class HydrantOutage(TypedDict, total=False):
    id: str
    hydrant_id: str
    reason: str
    expected_return_date: Optional[str]
    status: str
    notification_status: str
    notified_at: str
    ack_deadline: str
    acknowledged_at: Optional[str]
    acknowledged_by_user_id: Optional[str]
    escalated: bool
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PartLine(TypedDict, total=False):
    part_id: str
    qty: int
    unit_price_cents: Optional[int]
    status: str


class RepairWorkOrder(TypedDict, total=False):
    id: str
    hydrant_id: str
    source_inspection_id: Optional[str]
    description: str
    budget_cap_cents: Optional[int]
    status: str
    part_lines: List[PartLine]
    quoted_subtotal_cents: Optional[int]
    quoted_discount_cents: Optional[int]
    quoted_fee_cents: Optional[int]
    quoted_total_cents: Optional[int]
    actual_total_cents: Optional[int]
    created_by_user_id: str
    approved_by_user_id: Optional[str]
    last_rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Part(TypedDict, total=False):
    id: str
    sku: str
    name: str
    unit_price_cents: int
    on_hand_qty: int
    available_qty: int
    created_at: str
    updated_at: str
    version: int


class ISOSnapshot(TypedDict, total=False):
    id: str
    program_id: str
    weighting_profile: str
    status: str
    total_hydrants_in_scope: Optional[float]
    flow_coverage_pct: Optional[float]
    inspection_compliance_pct: Optional[float]
    iso_points: Optional[float]
    published_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
