"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    YARD_ADMIN = "YardAdmin"
    PROJECT_MANAGER = "ProjectManager"
    COMMERCIAL_APPROVER = "CommercialApprover"
    SHIPOWNER_REP = "ShipownerRep"
    CLASS_SURVEYOR = "ClassSurveyor"
    ENVIRONMENTAL_OFFICER = "EnvironmentalOfficer"
    SUBCONTRACTOR = "Subcontractor"


class RepairProjectStatus(str, Enum):
    DRAFT = "DRAFT"
    BID_SUBMITTED = "BID_SUBMITTED"
    CONTRACTED = "CONTRACTED"
    IN_DOCK = "IN_DOCK"
    WORK_COMPLETE = "WORK_COMPLETE"
    DELIVERED = "DELIVERED"
    CLOSED = "CLOSED"


class DockReservationStatus(str, Enum):
    BOOKED = "BOOKED"
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"
    CANCELLED = "CANCELLED"


class WorkItemStatus(str, Enum):
    PLANNED = "PLANNED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETE = "COMPLETE"
    CANCELLED = "CANCELLED"


class ChangeOrderStatus(str, Enum):
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class SurveyStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PASSED = "PASSED"
    FAILED = "FAILED"


class PermitStatus(str, Enum):
    APPLIED = "APPLIED"
    GRANTED = "GRANTED"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"
    EXPIRED = "EXPIRED"


class WarrantyClaimStatus(str, Enum):
    FILED = "FILED"
    ACCEPTED = "ACCEPTED"
    DENIED = "DENIED"
    CLOSED = "CLOSED"


class PricingMode(str, Enum):
    LUMP_SUM = "LUMP_SUM"
    TIME_AND_MATERIALS = "TIME_AND_MATERIALS"


class SurveyType(str, Enum):
    CLASS_RENEWAL = "CLASS_RENEWAL"
    CLASS_INTERMEDIATE = "CLASS_INTERMEDIATE"
    USCG_INSPECTION = "USCG_INSPECTION"
    LOAD_LINE = "LOAD_LINE"


class PermitType(str, Enum):
    HOT_WORK = "HOT_WORK"
    PAINT_SPRAY = "PAINT_SPRAY"
    BALLAST_DISCHARGE = "BALLAST_DISCHARGE"
    HULL_BLASTING = "HULL_BLASTING"


class OriginKind(str, Enum):
    BASE_SPEC = "BASE_SPEC"
    CHANGE_ORDER = "CHANGE_ORDER"
    WARRANTY_REWORK = "WARRANTY_REWORK"


class DockBerth(TypedDict):
    id: str
    name: str
    max_length_m: float
    max_beam_m: float
    max_depth_m: float
    daily_rate_cents: int
    created_at: str
    updated_at: str
    version: int


class Vessel(TypedDict):
    id: str
    name: str
    imo_number: str
    length_m: float
    beam_m: float
    draft_m: float
    owner_user_id: str
    created_at: str
    updated_at: str
    version: int


class Subcontractor(TypedDict):
    id: str
    name: str
    trade_codes: List[str]
    day_rate_cents: int
    created_at: str
    updated_at: str
    version: int


class RepairProject(TypedDict):
    id: str
    vessel_id: str
    dock_id: str
    contract_delivery_date: str
    warranty_days: int
    change_budget_cents: Optional[int]
    required_survey_types: List[str]
    status: str
    bid_total_cents: int
    awarded_price_cents: Optional[int]
    contracted_price_cents: Optional[int]
    actual_dock_in_utc: Optional[str]
    critical_path_days: int
    forecast_delivery_utc: Optional[str]
    ld_daily_rate_cents: Optional[int]
    provisional_ld_cents: int
    liquidated_damages_cents: Optional[int]
    delivered_at_utc: Optional[str]
    warranty_end_utc: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DockReservation(TypedDict):
    id: str
    project_id: str
    dock_id: str
    start_utc: str
    end_utc: str
    status: str
    dockage_fee_cents: int
    activated_at_utc: Optional[str]
    released_at_utc: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WorkItem(TypedDict):
    id: str
    project_id: str
    description: str
    trade_code: str
    pricing_mode: str
    quantity: Optional[float]
    unit_price_cents: Optional[int]
    estimated_hours: Optional[float]
    hourly_rate_cents: Optional[int]
    materials_cost_cents: Optional[int]
    duration_days: int
    depends_on_ids: List[str]
    requires_hot_work: bool
    subcontractor_id: Optional[str]
    origin_kind: str
    origin_change_order_id: Optional[str]
    line_total_cents: int
    status: str
    ready: bool
    completed_at_utc: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ChangeOrder(TypedDict):
    id: str
    project_id: str
    description: str
    trade_code: str
    pricing_mode: str
    quantity: Optional[float]
    unit_price_cents: Optional[int]
    estimated_hours: Optional[float]
    hourly_rate_cents: Optional[int]
    materials_cost_cents: Optional[int]
    duration_days: int
    schedule_delta_days: int
    proposed_cost_cents: int
    requires_owner_countersign: bool
    proposed_by_user_id: str
    commercial_approved_by: Optional[str]
    owner_approved_by: Optional[str]
    rejection_reason: Optional[str]
    status: str
    approved_at_utc: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Survey(TypedDict):
    id: str
    project_id: str
    survey_type: str
    surveyor_user_id: str
    scheduled_start_utc: str
    scheduled_end_utc: str
    result: Optional[str]
    deficiency_count: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Permit(TypedDict):
    id: str
    project_id: str
    permit_type: str
    valid_from: str
    valid_to: str
    status: str
    created_at: str
    updated_at: str
    version: int


class WarrantyClaim(TypedDict):
    id: str
    project_id: str
    work_item_id: str
    description: str
    filed_by_user_id: str
    status: str
    rework_work_item_id: Optional[str]
    denial_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int
