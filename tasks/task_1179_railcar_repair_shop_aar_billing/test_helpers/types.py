"""Domain types: entity TypedDicts, status enums, role enum (PRD §2-§3)."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Status / enum vocabularies
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    SHOP_ADMIN = "ShopAdmin"
    YARD_CLERK = "YardClerk"
    CAR_INSPECTOR = "CarInspector"
    REPAIR_FOREMAN = "RepairForeman"
    QUALITY_INSPECTOR = "QualityInspector"
    PARTS_CLERK = "PartsClerk"
    BILLING_CLERK = "BillingClerk"
    CAR_OWNER_REP = "CarOwnerRep"
    HANDLING_LINE_REP = "HandlingLineRep"


class ShopPosture(str, Enum):
    OPEN = "OPEN"
    CONSTRAINED = "CONSTRAINED"
    FULL = "FULL"


class CarOwnerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CREDIT_WATCH = "CREDIT_WATCH"


class RailcarStatus(str, Enum):
    ARRIVED = "ARRIVED"
    IN_SHOP = "IN_SHOP"
    READY_FOR_DEPARTURE = "READY_FOR_DEPARTURE"
    DEPARTED = "DEPARTED"


class InspectionStatus(str, Enum):
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    REOPENED = "REOPENED"


class DefectGroup(str, Enum):
    WHEELSET = "WHEELSET"
    AIR_HOSE = "AIR_HOSE"
    COUPLER = "COUPLER"
    SAFETY_APPLIANCE = "SAFETY_APPLIANCE"
    STRUCTURAL = "STRUCTURAL"
    BRAKE_BEAM = "BRAKE_BEAM"
    DOOR = "DOOR"
    OTHER = "OTHER"


class CauseCode(str, Enum):
    WEAR = "WEAR"
    HANDLING_DAMAGE = "HANDLING_DAMAGE"
    ACCIDENT = "ACCIDENT"
    UNKNOWN = "UNKNOWN"


class Severity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CONDEMNABLE = "CONDEMNABLE"


class DefectStatus(str, Enum):
    OPEN = "OPEN"
    ESTIMATED = "ESTIMATED"
    AUTHORIZED = "AUTHORIZED"
    REPAIRED = "REPAIRED"
    DECLINED = "DECLINED"


class Routing(str, Enum):
    SHOP = "SHOP"
    MOBILE = "MOBILE"


class AuthStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_AUTHORIZATION = "PENDING_AUTHORIZATION"
    AUTHORIZED = "AUTHORIZED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class ExecStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    SHOP_QUEUED = "SHOP_QUEUED"
    MOBILE_DISPATCHED = "MOBILE_DISPATCHED"
    IN_PROGRESS = "IN_PROGRESS"
    QA_REVIEW = "QA_REVIEW"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ResponsibleParty(str, Enum):
    OWNER = "OWNER"
    HANDLING_LINE = "HANDLING_LINE"
    SHARED = "SHARED"


class RepairLineStatus(str, Enum):
    ESTIMATED = "ESTIMATED"
    AUTHORIZED = "AUTHORIZED"
    FINALIZED = "FINALIZED"
    CANCELLED = "CANCELLED"


class PartStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REORDER_NEEDED = "REORDER_NEEDED"
    DEPLETED = "DEPLETED"


class WheelsetStatus(str, Enum):
    IN_STOCK = "IN_STOCK"
    MOUNTED = "MOUNTED"
    REMOVED = "REMOVED"
    CONDEMNED = "CONDEMNED"


class SlotStatus(str, Enum):
    OPEN = "OPEN"
    RESERVED = "RESERVED"
    OCCUPIED = "OCCUPIED"
    RELEASED = "RELEASED"
    BLOCKED = "BLOCKED"


class BrcStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    DISPUTED = "DISPUTED"
    ACCEPTED = "ACCEPTED"
    SETTLED = "SETTLED"
    WITHDRAWN = "WITHDRAWN"
    SUPERSEDED = "SUPERSEDED"


class CounterBillStatus(str, Enum):
    OPEN = "OPEN"
    ACCEPTED = "ACCEPTED"
    REBUTTED = "REBUTTED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"


class WarrantyClaimStatus(str, Enum):
    FILED = "FILED"
    VALIDATED = "VALIDATED"
    HONORED = "HONORED"
    DENIED = "DENIED"


# ---------------------------------------------------------------------------
# Entity TypedDicts (all entities carry id/created_at/updated_at/version)
# ---------------------------------------------------------------------------

class Shop(TypedDict, total=False):
    id: str
    name: str
    stalls: int
    stall_daily_hours: int
    dwell_free_hours: int
    dwell_rate_cents_per_hour: int
    warranty_days: int
    counter_window_days: int
    owner_watch_threshold_cents: int
    current_posture: str
    created_at: str
    updated_at: str
    version: int


class CarOwner(TypedDict, total=False):
    id: str
    shop_id: str
    name: str
    scac_code: str
    outstanding_balance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class HandlingLine(TypedDict, total=False):
    id: str
    shop_id: str
    name: str
    mark: str
    outstanding_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Railcar(TypedDict, total=False):
    id: str
    shop_id: str
    reporting_mark: str
    car_number: str
    owner_id: str
    handling_line_id: str
    built_date: str
    arrived_at: str
    departed_at: Optional[str]
    status: str
    shop_delay_hours: float
    projected_dwell_charge_cents: Optional[int]
    dwell_charge_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Inspection(TypedDict, total=False):
    id: str
    railcar_id: str
    status: str
    inspector_user_id: str
    completed_at: Optional[str]
    reopened_count: int
    created_at: str
    updated_at: str
    version: int


class DefectFinding(TypedDict, total=False):
    id: str
    inspection_id: str
    aar_defect_code: str
    defect_group: str
    cause_code: str
    severity: str
    location: str
    status: str
    created_at: str
    updated_at: str
    version: int


class WorkOrder(TypedDict, total=False):
    id: str
    railcar_id: str
    inspection_id: str
    routing: str
    auth_status: str
    exec_status: str
    responsible_party: Optional[str]
    owner_share_pct: Optional[int]
    estimate_total_cents: int
    final_total_cents: Optional[int]
    assigned_slot_id: Optional[str]
    mobile_crew_id: Optional[str]
    created_by_user_id: str
    authorized_at: Optional[str]
    completed_at: Optional[str]
    qa_review_entered_at: Optional[str]
    rework_count: int
    created_at: str
    updated_at: str
    version: int


class RepairLine(TypedDict, total=False):
    id: str
    work_order_id: str
    defect_finding_id: str
    job_code: str
    price_master_entry_id: str
    planned_parts: List[Dict[str, Any]]
    actual_labor_hours: Optional[float]
    actual_parts: Optional[List[Dict[str, Any]]]
    estimate_labor_cents: int
    estimate_material_cents: int
    estimate_total_cents: int
    final_labor_cents: Optional[int]
    final_material_cents: Optional[int]
    final_total_cents: Optional[int]
    responsible_party: Optional[str]
    owner_pct: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class PriceMasterEntry(TypedDict, total=False):
    id: str
    shop_id: str
    job_code: str
    description: str
    labor_rate_cents_per_hour: int
    mobile_labor_rate_cents_per_hour: int
    standard_labor_hours: float
    mobile_trip_surcharge_cents: int
    mobile_eligible: bool
    shared_split: bool
    effective_from: str
    effective_to: str
    created_at: str
    updated_at: str
    version: int


class PartItem(TypedDict, total=False):
    id: str
    shop_id: str
    part_number: str
    description: str
    unit_price_cents: int
    on_hand_qty: int
    reserved_qty: int
    available_qty: int
    reorder_threshold: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Wheelset(TypedDict, total=False):
    id: str
    shop_id: str
    serial_number: str
    flange_thickness_mm: float
    tread_wear_mm: float
    status: str
    mounted_railcar_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ShopSlot(TypedDict, total=False):
    id: str
    shop_id: str
    stall_id: str
    starts_at: str
    ends_at: str
    status: str
    reserved_work_order_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BillingRepairCard(TypedDict, total=False):
    id: str
    work_order_id: str
    supersedes_brc_id: Optional[str]
    status: str
    mobile_surcharge_cents: int
    submitted_total_cents: int
    owner_total_cents: int
    handling_line_total_cents: int
    net_settled_cents: int
    submitted_at: Optional[str]
    dispute_window_ends_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BrcLine(TypedDict, total=False):
    id: str
    brc_id: str
    repair_line_id: str
    job_code: str
    final_amount_cents: int
    owner_share_cents: int
    handling_share_cents: int
    accepted_credit_cents: int
    warranty_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class CounterBill(TypedDict, total=False):
    id: str
    brc_id: str
    items: List[Dict[str, Any]]
    total_countered_cents: int
    status: str
    filed_by_role: str
    filed_by_id: str
    filed_at: str
    created_at: str
    updated_at: str
    version: int


class WarrantyClaim(TypedDict, total=False):
    id: str
    shop_id: str
    repair_line_id: str
    failure_defect_group: str
    description: str
    claimed_rework_cost_cents: int
    credit_cents: Optional[int]
    status: str
    filed_by_role: str
    filed_by_id: str
    appeal_count: int
    created_at: str
    updated_at: str
    version: int
