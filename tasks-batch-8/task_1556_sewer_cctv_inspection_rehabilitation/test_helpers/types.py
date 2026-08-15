"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    DISTRICT_ENGINEER = "DistrictEngineer"
    CODER = "Coder"
    QA_REVIEWER = "QaReviewer"
    CREW_LEAD = "CrewLead"
    CUSTOMER_SERVICE_REP = "CustomerServiceRep"


class CycleStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class RehabStatus(str, Enum):
    NONE = "NONE"
    PLANNED = "PLANNED"
    IN_PROGRESS = "IN_PROGRESS"
    REHABILITATED = "REHABILITATED"
    WARRANTY = "WARRANTY"


class InspectionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    CODING = "CODING"
    QA_REVIEW = "QA_REVIEW"
    CERTIFIED = "CERTIFIED"
    VOIDED = "VOIDED"


class InspectionPurpose(str, Enum):
    BASELINE = "BASELINE"
    PRE_REHAB = "PRE_REHAB"
    POST_CIPP = "POST_CIPP"
    WARRANTY_RE = "WARRANTY_RE"


class DefectFamily(str, Enum):
    STRUCTURAL = "STRUCTURAL"
    OM = "OM"


class RehabMethod(str, Enum):
    CIPP_LINING = "CIPP_LINING"
    SPOT_REPAIR = "SPOT_REPAIR"
    FULL_REPLACE = "FULL_REPLACE"


class PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    EXECUTING = "EXECUTING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ExecutionStatus(str, Enum):
    ISSUED = "ISSUED"
    MOBILIZED = "MOBILIZED"
    IN_WORK = "IN_WORK"
    PUNCH_LIST = "PUNCH_LIST"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class BillingStatus(str, Enum):
    UNBILLED = "UNBILLED"
    INVOICED = "INVOICED"
    PAID = "PAID"


class MobilizationTier(str, Enum):
    MOB_SMALL = "MOB_SMALL"
    MOB_STANDARD = "MOB_STANDARD"
    MOB_LARGE = "MOB_LARGE"


class BypassStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"
    DEMOBILIZED = "DEMOBILIZED"
    CLOSED = "CLOSED"
    REJECTED = "REJECTED"


class NoticeStatus(str, Enum):
    QUEUED = "QUEUED"
    SENT = "SENT"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    EXPIRED = "EXPIRED"


class WarrantyStatus(str, Enum):
    OPENED = "OPENED"
    RE_INSPECTION = "RE_INSPECTION"
    UNDER_REPAIR = "UNDER_REPAIR"
    RESOLVED = "RESOLVED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


class FlowPhase(str, Enum):
    PRE_REHAB = "PRE_REHAB"
    POST_REHAB = "POST_REHAB"


class FlowStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"
    ANALYZED = "ANALYZED"


class PipeMaterial(str, Enum):
    VCP = "VCP"
    RCP = "RCP"
    PVC = "PVC"
    HDPE = "HDPE"
    CI = "CI"
    BRICK = "BRICK"


class ConnectionType(str, Enum):
    DIRECT = "DIRECT"
    WYE = "WYE"
    SADDLE = "SADDLE"


class NoticeChannel(str, Enum):
    DOOR_HANGER = "DOOR_HANGER"
    MAIL = "MAIL"
    SMS = "SMS"
    EMAIL = "EMAIL"


# --- Entity TypedDicts (common_fields: id + created_at + updated_at + version) ---

class SewerDistrict(TypedDict, total=False):
    id: str
    name: str
    ii_reduction_target_pct: float
    notice_lead_hours: int
    warranty_months: int
    budget_cents: int
    budget_committed_cents: int
    created_at: str
    updated_at: str
    version: int


class Technician(TypedDict, total=False):
    id: str
    full_name: str
    nassco_cert_number: str
    nassco_cert_expires_at: str
    capabilities: List[str]
    active: bool
    created_at: str
    updated_at: str
    version: int


class InspectionCycle(TypedDict, total=False):
    id: str
    district_id: str
    label: str
    window_start: str
    window_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PipeSegment(TypedDict, total=False):
    id: str
    district_id: str
    segment_ref: str
    diameter_mm: int
    material: str
    length_m: float
    install_year: int
    structural_grade: int
    om_grade: int
    quick_rating: Optional[str]
    structural_index: Optional[float]
    rehab_status: str
    last_rehab_completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Lateral(TypedDict, total=False):
    id: str
    segment_id: str
    address: str
    connection_type: str
    active: bool
    reinstated: bool
    created_at: str
    updated_at: str
    version: int


class CctvInspection(TypedDict, total=False):
    id: str
    segment_id: str
    cycle_id: str
    scheduled_at: str
    coder_id: str
    qa_reviewer_id: Optional[str]
    purpose: str
    status: str
    reject_count: int
    certified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# DefectObservation is append-only (PRD §2.5): carries ONLY id + created_at,
# never updated_at, never version.
class DefectObservation(TypedDict, total=False):
    id: str
    inspection_id: str
    pacp_code: str
    family: str
    grade: int
    distance_m: float
    clock_position: int
    extent_m: float
    created_at: str


class RehabPlan(TypedDict, total=False):
    id: str
    segment_id: str
    method: str
    basis_inspection_id: str
    status: str
    provisional_total_cents: int
    final_total_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class WorkOrder(TypedDict, total=False):
    id: str
    plan_id: str
    crew_lead_id: str
    execution_status: str
    billing_status: str
    mobilization_tier: str
    completed_at: Optional[str]
    warranty_expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WorkOrderLineItem(TypedDict, total=False):
    id: str
    work_order_id: str
    pay_item_code: str
    scheduled_qty: float
    installed_qty: Optional[float]
    unit_price_cents: int
    provisional_line_cents: int
    final_line_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class BypassPlan(TypedDict, total=False):
    id: str
    work_order_id: str
    window_start: str
    window_end: str
    pump_capacity_gpm: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CustomerNotice(TypedDict, total=False):
    id: str
    work_order_id: str
    address: str
    channel: str
    event_start: str
    sent_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class WarrantyCase(TypedDict, total=False):
    id: str
    segment_id: str
    work_order_id: str
    opened_at: str
    defect_summary: str
    re_inspection_id: Optional[str]
    status: str
    resolution_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FlowMonitoringPeriod(TypedDict, total=False):
    id: str
    district_id: str
    basin_label: str
    phase: str
    window_start: str
    window_end: str
    dry_weather_avg_gpm: Optional[float]
    peak_storm_gpm: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int
